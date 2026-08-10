# Syndicate TODO — closed items archive

Record of shipped work, split out of `docs/ai_context/todo.md` on 2026-07-26 to
keep the working list readable. **`todo.md` remains canonical for anything
outstanding** — start there, not here.

This file is a *record*. Any lesson from a closed item that should still change
what a future session does was deliberately **left in `todo.md`**, under
"Operational notes worth not rediscovering", so that it is read regardless of
whether anyone opens this file. If you find yourself needing to read this
archive to avoid repeating a mistake, that lesson was filed in the wrong place —
promote it back to `todo.md`.

**IDs are stable and never reused.** An ID appearing here is closed forever; new
work takes the next free number (see the counter at the top of `todo.md`).

---

## Closed 2026-08-10 — the memory excursion whose stage name was a bystander, and the instrument that could not see it (`#327`)


**Status: measured on production 2026-08-10, re-derived independently from the
raw logs rather than inherited. Not fixed. Filed at the `#285` lane's suggestion
after their verification; the instrument half is sharpened here.**

#### The excursion

refresh-worker `87cdd3e1`, pid 38 (started 15:59:12Z). Three consecutive
`post_mlb_sim_tick` samples:

```
16:32:36   pid38 1050.6   container 1923.9   accounted 1106.0
16:33:14   pid38 1867.4   container 2709.9   accounted 1896.4   <-- +816.7 / +786.0 / +790.5
16:33:48   pid38 1079.9   container 1928.4   accounted 1135.1
```

**All three metrics move together, which is the check that matters.** A `/proc`
artifact moves `rss_mb` alone; `container_memory_mb` comes from a different
source entirely (cgroup), so a lockstep +786MB there makes this real memory
rather than a bad read. Back to baseline within 72 seconds.

#### Why it deserves an ID separate from `#285`

`#285` owns a **ratchet** — ~11 MB/min, sustained, with or without the arena
cap. This is a **spike**: 817MB up and back in ~72s. Different shape, different
place (`post_mlb_sim_tick`, not the overview build everyone has been blaming),
and it does not move `#285`'s rate one way or the other.

**Headroom is the reason to care.** 1867MB process / 2710MB container leaves
~1.4GB. A hydrated overview measured at ~+700MB tonight, landing on the same
cycle, puts the container near **3.4GB against a 4GB cap**. Nobody has been
looking here.

#### The instrument gap, and it is worse than "a stage logs to stderr"

The `#285` lane found their RSS series was blind to this: **172 pid-38 samples
in the logs against 39 in the ring buffer at
`/api/ops/intelligence/memory-diagnostics` — they had been reading 23%.** And
the missing 77% is not a random sample; it carries the highest values:

```
post_mlb_sim_tick                n=34  max=1867.4  median=959.6   <- invisible
live_lens_tick_after_build_mlb   n= 9  max=1118.7  median=985.4   <- invisible
post_pool_assembled                    max=1044.1                 <- all they saw
```

**The sharpened mechanism, verified from the code here:** it is NOT that the sim
tick calls a different, humbler logger. **There are TWO functions with the SAME
NAME and only one of them persists:**

| | writes stderr | writes ring buffer |
|---|---|---|
| `pipeline/intelligence_state.py:2649` `_diag_log_all_process_memory` | yes | **yes** (`_diag_dump_checkpoint_to_disk`) |
| `scripts/run_refresh_worker.py:2086` `_diag_log_all_process_memory` | yes | **no** |

`run_refresh_worker.py:2306` calls `_diag_log_all_process_memory("post_mlb_sim_tick")`
— which reads, at the call site, exactly like the one that persists. **A reader
checking "is this stage instrumented?" sees the right function name and stops.**

This is the same shape as `#317`'s two board-snapshot write sites and `#105`
before it: a near-duplicate helper where only one copy receives the fix. The
repo keeps producing them. **Fix by extracting ONE helper, not by adding the
missing line to the second copy** — that is the lesson `#317` had to learn twice.

#### UPDATE 2026-08-10 — IT RECURS, IT IS EXCLUSIVELY `post_mlb_sim_tick`, AND IT IS NOT A CADENCE

Owned by the soccer-concurrency lane after `#282`/`#311` closed. **The
instrument fix `3e1096fb` is committed and NOT DEPLOYED**, so none of this came
from the ring buffer — it is all from the log channel, which was never blind.

**First attempt was worthless and the reason is reusable.** I compared every
sample against a fixed 1500MB threshold and got **1733 of 2967 samples over it
(58%)**. That measures the baseline, not an excursion, and it spanned four boots
whose baselines differ. **A threshold test cannot find a spike in a series whose
floor moves.**

The entry's own evidence was never a threshold — it was a *three-sample shape*
(1050.6 → 1867.4 → 1079.9). So the right test is local and boot-relative: how
far does a sample sit above the mean of its two immediate neighbours, never
measured across a restart. Over 5 hours, 3,914 samples, 5 boot segments:

```
15:32:27Z  post_mlb_sim_tick    933.2 -> 1586.7  (+653.5)  container 2296.9
16:14:53Z  post_mlb_sim_tick    937.4 -> 1430.9  (+493.6)  container 2347.3   +42.4 min
16:33:14Z  post_mlb_sim_tick   1120.5 -> 1896.4  (+775.9)  container 2709.9   +18.3 min
16:44:18Z  post_mlb_sim_tick   1160.6 -> 2030.8  (+870.2)  container 2792.7   +11.1 min
```

**1. It recurs.** `n=4` in 5 hours, not the `n=1` this entry recorded. The
16:33:14Z event is the one already filed here (1896.4 accounted vs the 1867.4
pid-38 RSS quoted above — different fields, same event).

**2. Exclusively `post_mlb_sim_tick`, and that is threshold-robust.** At a
400MB bar, **4 of 4**. Dropping the bar to 250MB gives 8, of which 5 are this
stage and the three others are all `live_lens_tick_*` at 287–380MB — **every
excursion above ~490MB is `post_mlb_sim_tick` and nothing else is close.**
Checking two thresholds matters because `n` is otherwise an artefact of the bar
I happened to pick.

**3. It is NOT a cadence, and this entry's caution was right.** Gaps are 42.4,
18.3 and 11.1 minutes — scattered, not periodic. Do not build a "spikes every N
minutes" claim; that remains unsupported with the sample size larger, not
smaller.

**4. THE APPARENT GROWTH IS NOT A TREND CLAIM.** Both the excursion size
(+653 → +494 → +776 → +870) and the floor it launches from (933 → 937 → 1121 →
1161) look like they are climbing, and container peak went 2297 → 2793. **That
is four points, and this file records the same error at least three times** —
the "accelerating OOM loop" from three boot gaps, the 5-sample live-lens median,
the n=7 memory peak. **I am explicitly not claiming a trend.** It is worth
re-measuring over a longer window; it is not worth acting on. [[a rate, not a count]]

**Headroom, stated as the reason to care:** peak container 2792.7MB against the
4096MB cap — **68%**, from a stage nobody was watching, with the hydrated
overview (~+700MB) able to land on the same cycle.

#### ATTRIBUTION 2026-08-10: `post_mlb_sim_tick` IS A BYSTANDER. FIVE causes eliminated (the fifth retracted, then RESTORED on a direct test), none confirmed

**The stage in the name did not allocate the memory.** At every one of the four
excursions the tick's own `MLB_SIM_TICK` meta reports **every sub-feature
gated**:

```
lookAhead            launched=false  within_check_interval
lookAheadDay2        launched=false  within_check_interval
mlbDailySim          launched=false  intelligence_pipeline_busy
mlbEveningNextDaySim launched=false  before_evening_window
mlbStatcastRefresh   launched=false  within_check_interval
```

**The tick launched nothing and did a handful of gate checks.** It cannot be
holding 817MB. `post_mlb_sim_tick` is simply the stage whose sample lands where
the memory already is — **the label marks the OBSERVER, not the ALLOCATOR**, and
anyone optimising the sim tick on the strength of this stage name will be
working on the wrong code. That is the single most useful thing in this entry.

#### Eliminated, each with its own evidence

**1. NOT a child process.** `accounted_rss_mb` sums every process in the
container, so a sim subprocess would look identical. It is not one — the growth
is inside the long-lived worker:

```
15:32:27  pid 39  +681.1MB of +655.2 total   (104% in-process)
16:14:53  pid 38  +503.5MB of +503.5 total   (100%)
16:33:14  pid 38  +816.7MB of +790.5 total   (103%)
16:44:18  pid 38  +878.5MB of +878.5 total   (100%)
```

**No new processes at any peak.** (>100% because one other process exited in the
same interval.)

**2. NOT the intelligence overview thread.** refresh-worker is one multithreaded
process, so a background thread could hold it and no per-process metric could
tell. Tested rather than assumed: `build_candidate_pool_start` /
`OVERVIEW_SPORT_BEGIN` follow each peak by **+83s, +88s, +75s, +72s** and read
**949.8 / 957.2 / 1121.4 / 1181.3 MB** — baseline. The overview builds *after*
the excursion has already drained.

**3. NOT a large artifact read.** The whole keyvalue store is **37.04MB**, largest
single key **8.39MB**. No parse of that can reach 800MB.

**4. NOT the `#322` book-grid tick** — the most attractive candidate, since it
reads the 207MB MLB `book_quotes` shard uninstrumented between samples.
**Correlation is suggestive and the mechanism does not survive:** every peak
follows a `BOOK_GRID_TICK` by **2.5 / 4.9 / 3.2 / 3.8 min**, but samples are
~30s apart, so a direct allocation would surface at the *next* sample, not five
minutes later. Decisively, there are **13 book-grid ticks against 4 peaks** in
the same window — if it were the cause it would fire three times as often as it
does. **A correlation that requires the effect to arrive 5 minutes late and skip
two thirds of its causes is not a mechanism.**

#### What that leaves, stated as a search space rather than a suspicion

In-process, in the long-lived worker, 493–878MB, released within ~72s, **not
aligned with any instrumented stage**. Every named stage around the peaks reads
baseline. So the allocator is in an **uninstrumented gap** — and one is already
visible: the live-lens loop's last stage sample (`live_lens_tick_after_nfl`)
precedes its own `TICK_COMPLETE` by ~18s, with the publish sweep inside that
window.

**Not claimed:** that the live-lens publish sweep is the cause. It is the
largest unlit gap adjacent to the peaks, which makes it where to point the next
instrument, not an answer. **That instrument was then built and it eliminated
the candidate — see below.**

**The method note.** Every elimination above came from a field already in the
payload — process tables, tick meta, stage timings. None needed new code.
[[read the field you already have]]

#### REGIME BOUNDARY — EVERY MEASUREMENT IN THIS ENTRY PREDATES 2026-08-10 21:56Z

`SYNDICATE_HYDRATED_OVERVIEW_MIN_REBUILD_SEC=900` was set at **21:56Z** and
verified firing at 22:08:27Z across all 8 sports (board still built,
`count=239`, on cached overviews). **The hydrated MLB pass — measured at +2.9GB
in 73s — now runs at roughly half its previous frequency.**

Everything below was measured **before** that: the `n=4` excursion table
(15:32–16:44Z), the 15-cycle publish-sweep table (20:33–21:07Z), the
`container_peak` climb 1155 → 2230MB, and the 21:16:54Z mid-sweep catch. **They
describe a noisier background than the one that exists now and are not directly
comparable with anything sampled after 21:56Z.**

Two consequences, and the second is easy to get backwards:

- **Excursions should be EASIER to isolate now.** A quieter baseline means a
  493–878MB in-process allocation stands out further from it.
- **The `container_peak` series is regime-split.** A "the baseline climbs
  1155 → 2230MB" claim is about the old regime. Re-derive it before reusing it —
  and note the same trap the entry already records: **a fixed threshold over a
  moving baseline measures the population, not the exception**, and the baseline
  just moved for a new reason.

#### 5. RESTORED, on the test the first version was never held to. The publish sweep is NOT the allocator

**Read this before the retraction below, which it supersedes.** The retraction
was right to make — the instrument really was blind — but the inference drawn
from it was weaker than I presented, and the direct test now says so.

**THE DECIDING OBSERVATION, 2026-08-10 22:40:42Z:**

```
excursion  rss 1389.0MB  container 2546.9MB  +529.5MB above neighbours
           NOT inside any publish sweep window
           nearest sweep 22:42:50-22:42:52, 127s away
```

**+529.5MB is squarely in the 493–878MB `#327` class, and no sweep was
running.** An excursion of the same magnitude occurs without the publish path,
so **the sweep is not necessary for it.** That is a direct exclusion, not a
magnitude argument.

#### THE NUMBER THAT SHOULD HAVE TEMPERED MY RETRACTION: a 20% base rate

Measured over 2,012s: **14 completed sweeps, 403s of total sweep time — a 20.0%
duty cycle.** So a randomly-timed excursion lands inside a sweep **one time in
five.**

**The 21:16:54Z coincidence I overturned an elimination on was a 1-in-5 event.**
I reported it as though it implicated the publish path. It did not: it was the
expected outcome a fifth of the time, and I never computed the prior before
acting on it. Coincidence with a process that is running 20% of the time is
close to no evidence at all.

**This is the same defect as the one it replaced, pointed the other way.** The
first elimination came from an instrument that could not see the event; the
retraction came from a coincidence whose base rate I did not check. Both were
confident, both were about the publish path, and both were wrong for reasons
available at the time. [[a rate, not a count]]

#### Three independent grounds now, which is why this one should hold

1. **Necessity fails.** A +529.5MB excursion with no sweep running (above).
2. **In-sweep sampling finds nothing.** Five sweeps of 47–55 artifacts,
   up to 43.3s and 22 polls, **max lift +14.5MB** above their own endpoints —
   on an instrument that reads the same cgroup counter as the excursion and
   therefore *cannot* miss a real spike in its own window.
3. **The one coincidence was expected.** 20% duty cycle, n=1.

**Still not claimed:** what *does* allocate it. This restores an elimination; it
does not identify a cause. Five eliminations, cause unattributed.

**Method note, and it is the reusable part.** The question that resolved this
was not "how big can the sweep get" — sweep size was always a proxy, and my own
`LARGE_SWEEP=60` threshold turned out to be unreachable (sizes plateaued at 47,
having plateaued at 34 earlier; the 73–103 in the loop's comment may describe a
configuration that no longer exists). **The question that resolved it was
whether the excursion needs the sweep at all.** Necessity is cheaper to test
than magnitude and it does not depend on catching the biggest case.

#### 5-superseded. RETRACTED — the publish sweep is BACK, and my instrument's blind spot is why I got it wrong

**READ THIS BEFORE THE ELIMINATION BELOW. I retract it.** The excursion was
caught happening *inside* a publish sweep, and my `before`/`after` pair is
structurally incapable of seeing it.

```
21:16:18  live_lens_publish_before   rss=1081.5   container=2470.5
21:16:54  post_mlb_sim_tick          rss=2051.7   container=3459.1   <-- +970MB, MID-SWEEP
21:17:11  live_lens_publish_after    rss=1233.9   container=2628.9   published=94 elapsed=53.6
```

**A 94-artifact, 53.6-second sweep. Thirty-six seconds in, RSS was +970MB above
the sweep's own `before` sample — and back down before its `after` sample.** The
endpoints report a +152MB delta across an event whose peak was +970MB.
`container` hit **3459.1MB, 84% of the 4096 cap** — the highest reading recorded
tonight.

**A BEFORE/AFTER PAIR CANNOT MEASURE A TRANSIENT ALLOCATED AND RELEASED BETWEEN
ITS ENDPOINTS.** I designed the instrument, argued an elimination from it, and
the elimination was an artifact of the instrument's blind spot. Same class as
every other failure in this file — an instrument answering rather than erring —
except this one is mine, built *after* writing that lesson down twice.
[[instrument blindness]]

**And the sample that produced the elimination was the wrong population.**
Sweeps of 15–34 artifacts have small deltas because they are small sweeps. The
73–103 range the loop's comment cites **does occur** — 94 and 99 artifacts,
observed 21:15–21:17Z — I simply had not caught one in the first 36 minutes and
generalised from the small ones. The caveat I attached ("max observed 34, a
non-linear blow-up is not formally excluded") was pointing exactly at what then
happened, which is an argument for weighting one's own caveats more heavily
than one's conclusion.

**Correction to a number I published:** `b9b77eaf` says the sweep accounted for
**−8%** of the excursion. That came from my watcher pairing `befores[0]` with
`afters[-1]` across a ±120s window spanning **three** cycles. The correct
within-cycle delta is **+152.4MB**, and the mid-sweep peak is **+970MB**. The
−8% figure is void.

#### What is now claimed, and what still is not

**Claimed:** the excursion is coincident with a large publish sweep, and the
publish path is a live candidate again. One observation.

**NOT claimed:** that the sweep causes it. Coincidence with a 53.6s window that
covers a large share of the cycle is weak on its own, and the four other
eliminations are unaffected. **What would settle it:** sampling *inside* the
sweep — per-artifact or on a timer — rather than at its boundaries. That is the
next instrument, and the reason to build it is that the current one has now
demonstrably failed at exactly the case it was built for.

#### The superseded elimination, kept because the data is real and the reasoning is instructive

`489ddbb5` lit the gap (`live_lens_publish_before` → `after`, plus the pull at
cycle start). Live on refresh-worker from **20:32:47Z**. **15 paired cycles**:

```
published  elapsed_s   d_container    d_rss      container_peak
   15          3.4        +43.3        +9.4         1155.5
   23          7.1       +199.7       +78.0         1570.0   <- outlier, see below
   15          8.2        +18.8        +0.0         1670.6
   15          5.1        -13.7       -26.3         1686.5
   15          1.8         -0.5        +0.0         2039.5
   15         35.3        -41.2       -41.7         2049.2
   15         12.9         -0.5        +0.0         2077.9
   15          7.7         +0.3        +0.0         2099.4
   15          2.3         -7.3        -0.3         2357.3
   15          4.7        +15.8       +16.2         2166.8
   15          4.9         +3.4        +3.2         2208.0
   17          5.6         -8.0        -1.0         2202.6
   30         13.8         +2.6        +0.0         2230.3
   32          3.7         -0.4        +0.0         2240.5
   34         47.3        +12.9       +12.9         2209.9
```

**Two independent reasons this is not the 493–878MB allocator:**

1. **Wrong magnitude by one to two orders.** Excluding the outlier, every cycle
   sits within ±44MB and most within ±20MB. **Many are NEGATIVE**, which is what
   a sweep whose allocations are freed before the after-sample looks like
   against a drifting baseline.
2. **No scaling with sweep size, which is the load-bearing test.** The *largest*
   sweep (34 artifacts) cost **+12.9MB**; a 15-artifact sweep cost **+43.3MB**.
   Marginal cost across the observed range is **−1.60 MB per artifact** —
   negative, i.e. no relationship at all. A linear model predicting ~500MB at
   103 artifacts is not merely unsupported, it is contradicted in sign.

**The `elapsed_seconds` check closes the obvious objection.** The loop's own
comment cites sweeps of "48–74s per cycle at 73–103 artifacts", so the natural
rebuttal is that only small fast sweeps were observed. **A 47.3-second sweep was
observed and cost +12.9MB** — squarely inside the cited duration band. Duration
does not buy memory here either.

#### The caveat that keeps this at "eliminated", not "excluded"

**Max observed sweep is 34 artifacts against the 73–103 the comment cites.** The
flat-to-negative slope from 15→34 makes a *linear* blow-up at 103 untenable, but
a **non-linear** one is not formally excluded. Steady state is ~15/cycle rising
to ~34 as the worker warms, so a 73–103 sweep likely needs a batch write and may
be rare. A watcher is running for one.

**And one point is unexplained: 23 artifacts → +199.7MB**, larger than every
bigger sweep in the table. Whatever produced it, **it was not sweep size** —
which makes it interesting rather than dismissible: it may be the same
uninstrumented something the excursions are, caught in passing.

#### A thing visible only because the deltas are near zero

`container_peak` climbs **1155 → 2230MB across 25 minutes** while the publish
deltas hover around nothing. That is `#285`'s ratchet accumulating underneath,
entirely independent of this path — and a standing reminder that **the baseline
moves on its own while you are measuring deltas against it.** A fixed threshold
over this series would have flagged the tail and called it an excursion.

#### A correction to my own instrumentation claim

I wrote that the sample "carries `published_count`/`failed_count`/
`elapsed_seconds`, so one line beats correlating two log streams". **True of
stderr, FALSE of the web-visible record.** `update_process_memory_high_water`
persists a fixed subset — `stage`, `peak_mb`, `container_memory_mb`,
`accounted_rss_mb`, `pct_of_max`, `observed_at`, `pid`, `processes` — and drops
arbitrary `**extra`. So `high_water` shows `published_count=None`.

**I nearly reported that `None` as evidence the sweep had crashed**, since my
own code sets those fields to `None` only on the exception path. It is the
schema, not a crash. Checking the emitter before interpreting the absence is the
only reason a false finding did not go out. [[absent signal is about the emitter]]

Small gap worth closing when something else deploys: **a peak without its
artifact count is a number without its denominator**, and the peak is exactly
where that denominator is wanted.

#### What is NOT claimed

- **Not accumulation.** It returns in 72s. `#285`'s ratchet is unaffected.
- ~~**Not recurring.** This is **n=1 in a 39-minute window**.~~ **SUPERSEDED —
  it DOES recur: `n=4` in 5 hours (see the 2026-08-10 update above).** The
  original was correct for the window it had; a 39-minute window simply could
  not see a ~75-minute inter-arrival gap. **The half of this bullet that
  SURVIVED is the important one: it is still NOT a cadence** — gaps of 42.4,
  18.3 and 11.1 minutes are scattered, and "spikes every N minutes" remains
  unsupported with the sample four times larger.
- **Not attributed to a cause.** Nothing here says what allocates the 817MB.
- **Not `_keyvalue_backed` (`#324`).** That change only re-routes which transport
  a write takes, the spike is inside the sim tick, and the trim/gc figures on
  this boot match the previous one.

#### Where it came from, because the path matters

I found the 1867.4 reading incidentally while sampling process lists for an
unrelated zombie question (`#324`), and handed it over rather than sitting on it
because it fell outside the range the `#285` lane was reasoning about. They
verified it, and it exposed a blind spot in their own instrument that they could
not have found from inside it. **Both halves needed the handoff** — the number
was useless to me and the instrument gap was invisible to them.

## Closed 2026-08-10 — the board that computed and never landed, and the OOM nobody could diagnose (`#317`, `#318`)

| # | What shipped |
|---|---|
| `#317` | **The intelligence board computed correctly every cycle and reached production never.** The brief this started from said `STATE_PERSIST_BEGIN` never fires and therefore the persist "is not being reached" — false. It fired (`candidate_count=150`, 20:09:16Z), and `write_latest_intelligence_state` ran to completion. The board died one layer lower, on **both** transports at once: keyvalue refused it on size (`27,638,247` bytes against an `8,388,608` ceiling) and the artifact fallback got `HTTP Error 502` because web was OOM-cycling. `board_snapshot*.json` failed one step earlier still, at `SKIP_NOT_ALLOWLISTED` — **deliberately**, and it must stay that way (`artifact_publisher.py`: web's only reader consults keyvalue, never disk, so allowlisting it would push 33.5MB/cycle at a file nothing reads). **Why empty boards wrote and good ones did not: size was the discriminator** — the two snapshots that did land (19:23Z, 19:38Z) both carried `candidate_count: 0`, and a zero-candidate payload fits. Fixed under `#322` by compressing the payload rather than aliasing it (aliasing was played out at ~13MB; what remained was not duplicated): `14,286,066 → 811,656` bytes at 313 candidates. |
| `#318` | **Web OOM-killed every ~14 minutes on a 2GiB limit — 18 `server_failed` between 2026-08-09T02:40Z and 2026-08-10T03:46Z** — and nothing on the service could say why: `CONTAINER_MEMORY` reported `memory_current_mb 1877.1 / 91.7%` next to a `PROCESS_TREE_MEMORY` reading `self_rss_mb 189.1, child_count 0`, with **1.7GB unattributed** and no way to split reclaimable page cache from anonymous. `_read_container_memory_stat()` had read `anon`/`inactive_file` since `#79` and `memory_headroom_snapshot` already used it; it was simply never wired into the line people read. Now it is. |

**Commits.** `7cceb781` (`memory_observability.log_container_memory` emits `memory_anon_mb` / `memory_inactive_file_mb` / `memory_reclaimable_mb` / `memory_unreclaimable_mb` / `memory_unreclaimable_pct_of_max`; absent keys stay **absent**, not `0`, so an unparseable cgroup cannot read as "plenty of room"; +2 tests, `tests/test_memory_observability.py` 10 passed). `04ab001d`, `93fae5a8`, `b975c26b`, `aad29190` (findings and two retractions). The `#317` cure itself is `#322`'s (`ef3f6a2b`, `863ecd59`, `2f6dcece`); the OOM recovery is most likely `cb3946a2` (`#285`, glibc arena cap).

**Verified in production 2026-08-10T15:0xZ**, refresh-worker `cb3946a2` / web `d25b1aaa`:

```
KEYVALUE_WRITE_REJECTED   0   in 13:30-15:30Z      (was: every cycle)
STATE_PERSIST_BEGIN      30   in 13:30-15:30Z, incl. candidate_count=150
snapshot_generated_at         2026-08-10T10:06:31-05:00, advancing (was frozen 42 min)
top_opportunities_count     150  (was 0)
/api/home                   200  (was 000/502)
web server_failed             0  in the ~11h since the 03:46:49Z deploy
```

The `kvrej=0` reading is only meaningful *because* `persist=30` with a populated
`150` accompanies it — `kvrej=0` with `persist=0` would mean nothing was
attempted, not that anything succeeded. That pairing was the stated success test.

**Instrument confirmed live, not merely shipped** — `git merge-base --is-ancestor 7cceb781 d25b1aaa` → true, and it is emitting.

**Three wrong root causes were published on `#318` before the right method was
applied**, all by the same lane, all retracted in the file rather than deleted:
the worker's `artifacts/export` pulls; a small-file publish flood; and page
cache. The publish-flood claim carried byte counts and source IPs, which made it
*read* rigorous — it failed on a missing concurrency denominator
(`WEB_CONCURRENCY=2 × GUNICORN_THREADS=4` is **8** request slots, not 60) and on
coverage (publishes preceded 5 of 6 kills; the 6th had zero traffic and landed
during `bootstrap_data_root`, i.e. was a crash-loop echo, so the six kills were
never six independent data points). `#319` later measured the flood **innocent**
outright. The surviving lessons are promoted to `todo.md`'s Operational notes.

Full writeups in `todo.md`'s git history (this file's entries as of `aad29190`).

## Closed 2026-08-05 — WNBA CI test-order pollution + empty-slate message mismatch (`task_b4637457`)

| # | What shipped |
|---|---|
| `task_b4637457` | `python -m unittest tests.test_archives` (what CI actually runs) was reporting 6 failures. Two distinct root causes, both fixed in one commit: (1) plain `unittest`'s alphabetical-by-method-name test order (not file order) plus a wall-clock-TTL cache in `wnba/cards.py` keyed only on `(date, event_ids, allow_stored_date_fallback)` let one test's mocked payload leak into a same-key later-running test — `tests/conftest.py` already resets this cache class for pytest, but its autouse fixtures never load under plain `unittest`; fixed with real `setUp`/`tearDown` on `DateArchiveHelperTests` (`tests/test_archives.py`), which run under both runners. (2) `has_games_for_date("1900-01-01")` fell through to a live ESPN call that fails offline and returns `None` rather than `False`, so the wrong empty-state message was chosen; fixed with a founding-year (1997) guard in `wnba/sources.py`. |

Commit: `53cf342a` (2 files). Verified: `unittest tests.test_archives` 383/383 (was 6 failures); `pytest tests/test_archives.py` unaffected (381 passed/2 skipped); 145 tests across the other 6 files touching `has_games_for_date` still pass. Deployed to all three Render services (web, refresh-worker, live-odds-worker) after confirming no in-flight MLB sim — `has_games_for_date` runs in the live request path, so this one needed the deploy, unlike a test-only fix. Full writeup in `todo.md`'s git history (was the top "RESOLVED 2026-08-05 (`task_b4637457`)" entry before this archival pass).

## Closed 2026-07-30 — Games-strip/soccer-league session (#162, #164, #165, #166)

| # | What shipped |
|---|---|
| **162** | Soccer candidates show the real league ("MLS", "La Liga") instead of the generic "Soccer" sport label — `home.py`'s `_append_game_bet_candidate` and `intelligence.py`'s `_steam_candidates_for_sport` both prefer `game.get("league_display")` (stamped by `soccer/cards.py`'s game-dict constructors) over the static per-sport config name. |
| **164** | WNBA pregame props were silently dropped for TODAY's slate (real picks existed in `recommendations_slate_<date>.json` but zero reached the board) — root cause: `_prop_item_from_rank_card` (home.py) never set a `game_id`/`gamePk`/`event_id`, so `_build_sport_overview`'s hydration-intersection filter excluded every one of them. New `_backfill_prop_row_game_id` matches each row's team abbreviations against `home_games`, wired into `_WNBADataProvider.pregame_props`. |
| **165** | Duplicate Games-strip mini-cards for the same live game — went through 3 live-broken versions (matchup-only merge hid a real different-date game; exact date-key broke the original same-day merge; date-clustering still missed a candidate whose date field was itself wrong, not missing) before landing on clustering by **live-chip identity** first, date-compatibility only for chip-less groups. See the Operational note in `todo.md` — this one is worth reading, not just the summary here. |
| **166** | Soccer steam candidates' `game_date` was the board's scan date, not the individual match's real kickoff date (e.g. 7 real Saturday MLS matches all showed "Fri Jul 31"). First fix (season-schedule fuzzy team-name cross-reference) shipped with two real bugs of its own (wrong field-access pattern reading a different structure's shape; no disambiguation for team pairs meeting twice in a season) before being replaced entirely — the raw OddsAPI odds row already carries its own `commence_time` column directly, no cross-referencing needed at all. See the Operational note in `todo.md`. |

Commits: `8ea2d8b1` (#162) · `409677df`+`fa7d0426`+`cd5b6714`+`940024f2` (#164/#165 + 3 follow-ups) · `2f926f40`+`99293914`+`969e8a44` (#166 + 2 follow-ups). All verified live in production (not just tests) before this session ended, including a full re-check of the rendered board after each fix. Landed alongside two other concurrently-active sessions in the same shared checkout (`#161` Layer 1 closing-line, `#163` Ask The Syndicate player history) — coordinated via send_message rather than colliding on files.

## Closed 2026-07-30/31 — Ask The Syndicate MLB player history + advanced analytics (#163)

User asked for Ask The Syndicate's MLB answers to show real player history and advanced matchup analytics alongside the existing sim-only tables (motivating example: "Eury Perez outs" returning only SmartSim tables, no real data). Shipped across four commits in one continuous session, each one surfacing the next real gap live in production rather than in a vacuum:

| # | What shipped |
|---|---|
| **163a** | New MLB recent-form index (`syndicate/features/mlb/player_game_log.py`) — MLB had no per-player game-log artifact at all (unlike NBA/WNBA/NHL). Scans mirrored `feed_live` files into `mlb_pitcher_game_log.csv`/`mlb_batter_game_log.csv`, incremental by `(game_pk, player_id)`; `run_mlb_daily_sim_job.py` keeps it current automatically. New `_mlb_player_history_evidence` evidence fetcher adds "Last N starts/games", "History vs {opponent}", an actual-stat bar chart, and an "Advanced Statcast profile" table (the underlying Statcast feature file existed but was stale/unused — regenerated for the full 2026 season). Along the way: fixed `_mlb_bvp_evidence`'s pitcher branch silently returning nothing for a young pitcher with sparse career BvP (now an explanatory note + park/weather), and a real pre-existing bug in `_name_matches`/`_person_matches` — no diacritic folding, so "Perez" never matched a *stored* "Pérez" (MLB Stats API returns some names accented, others not) — this was the actual reason the original "Eury Perez outs" screenshot showed nothing at all. |
| **163b** | Real production bug, found via the user's own live test immediately after 163a deployed: "Eury Perez outs" still returned zero visuals. Root cause — Render gives web and refresh-worker separate, non-shared disks; the new CSV/Statcast-feature paths were never added to `artifact_publisher.HOT_ARTIFACT_PATTERNS`, so they built correctly forever on refresh-worker and never once reached web (the same gap class as three prior incidents documented in that file's own comments — see the new Operational note in `todo.md`). Fixed the allowlist, and reordered `run_mlb_daily_sim_job.py` so the game-log bootstrap runs *before* the publish sweep (which only picks up files with mtime newer than the job's start epoch). |
| **163c** | The weekly Statcast refresh from 163a was wired into `scripts/unified_daily_update.ps1`, which turned out to never run in production at all (not referenced by `render.yaml` or any GHA workflow — confirmed live the feature file stayed stuck on a stale generation date through two full deploys). Properly wired into `live_refresh_loop.py` (the actual persistent refresh-worker loop) as a new staleness-gated gate mirroring the existing MLB daily-sim gate's pattern (deferred while a sim is active or memory headroom is low, launched as a detached subprocess, PID-verified status file). Enabled via `SYNDICATE_ENABLE_MLB_STATCAST_REFRESH_TRIGGER` on refresh-worker only. |
| **163d** | Live user feedback on the shipped feature, addressed same session: chart values were hover-tooltip-only (`renderVisualChart` now shows a visible label above each bar); "Eury Perez outs" charted strikeouts regardless of which stat was asked (new `_mlb_pitcher_chart_stat` picks among outs/K/BB/ER/pitches from the actual question wording); added an "Opposing lineup Statcast approach" table (today's lineup's own xwOBA/Barrel%/HardHit%/K-mult, sorted by biggest matchup threat) — previously only the pitcher's own profile was shown, not the batters he's actually facing. |

**Also found, not fixed** (see `todo.md` #167): `source_roots.py`'s `repo_root_from` has an off-by-one for callers 2 subdirectories deep instead of 3 (masked in production by an always-set env var, real trap for local dev without it).

Commits: `fdb6861a` (163a) · `1ea9b4cf` (163b) · `f77d872c` (163c) · `272b496d` (163d). All four deployed to web + refresh-worker and verified against real production queries (not just tests) before this session ended — including watching a real forced resim complete on refresh-worker's actual disk to confirm the artifact-publish fix worked end-to-end, and a live browser check of the rendered chart values. 293/299 relevant tests passing (6 pre-existing, confirmed-unrelated flaky failures). Landed alongside two other concurrently-active sessions in the same shared checkout (Games-strip/soccer-league #162/#164-166, and a separate #161-part-2/production-outage session) — coordinated via send_message, and one of those sessions' own urgent production hotfix (`c44c02cc`/`ac03e46d`, an unrelated broken import) landed cleanly underneath 163c/163d with no collision.

## Closed in the 2026-07-25/26 session

| # | What shipped |
|---|---|
| **14** | OddsAPI quota instrumentation — all 9 call sites |
| **16** | MLB market audit (findings live on in #53) |
| **17** | Core game lines → slate endpoint, 45 → 3 credits |
| **18** | NCAAF regions `us,us2,eu,uk` → `us` |
| **25 (Phase 0)** | Fail-closed refresh guard + atomic artifact writes |
| **40** | `render.yaml` drift reconciled, `plan: pro` pinned |
| **41** | Scoped-resim regression test |
| **44a** | Soccer market board cache + resim detection — `12742e6c` |
| **44b** | Soccer event-driven resim path — `b9f70d3a`, ships **dark** |
| **46** | `sim_run_status` self-resolution — `f6a013e3` |
| **47** | Soccer added to the worker's sport list |
| **48** | Odds prices removed from the sim fingerprint |
| **49** | `test_ops` triage |
| **50** | Artifact-export ceiling |
| **54** | Quota store made O(1) |
| **55** | Sim ↔ board-build alternation, **both** directions |
| **29** | Cross-type duplicate candidates — every pick rendered twice |
| **73** | Ranking signals computed but never applied to the order |
| **58** | Basketball quarter sim vectorised — 215ms → 2.9ms/game (73×) |
| **57** | Board build stays on refresh-worker, upgraded to pro/4GB |
| **60** | Keyvalue payload ceiling — oversized writes fail loudly |
| **63** | Mutual-deferral starvation invariant test |
| **64** | Candidate pool's last stage made visible — `a1638c39` |
| **67** | Soccer game state derived from the clock, not a frozen `status_state` |
| — | Central-date sweep, 14 call sites + ratchet test (`tests/test_slate_date_timezone_discipline.py`) |

### Detail worth keeping

- **73 — ranking signals computed but never applied.** A "highest confidence"
  query and a "highest upside" query returned **byte-identical** orderings. The
  risk profile parsed correctly and reached `preferences`; nothing consulted it.
  Four separate signals, all fully implemented and all inert:
  - `_risk_profile_score_adjustment` and `_market_specific_score_adjustment`
    were **dead code** — defined, never called from anywhere. So `score` was
    `edge x confidence - tier_penalty` and nothing else. Both are no-ops by
    construction outside their trigger (`balanced` profile / no requested
    markets), so wiring them only moves rankings for queries that actually
    expressed a preference.
  - `advanced_ready` appeared nowhere in the board sort, and in the scorer only
    as a ≤0.05 nudge to confidence — far too small to act as the gate its name
    implies. A candidate with missing model inputs could outrank a ready one on
    raw edge.
  - `source_summary_score` (the qualitative read of a basketball prop's
    recent-form writeup) was computed, surfaced in the analysis table and chart
    series, and never ranked on.
  - **`score` itself was absent from the board sort**, which ordered on raw
    `simulated_edge` — a single component outvoting the composite that contains
    it. Fixing the scorer alone changed nothing a user could see; ordering is
    decided in *two* places (`score_candidate` and
    `build_intelligence_board_contract`) and both had to change.
  - ⚠️ **Where a signal goes matters as much as whether it is used.** Folding
    `source_summary_score` into `score` at its native ±3.0 weight regressed
    `test_intelligence_query_prioritizes_ready_advanced_inputs` — a qualitative
    text signal overrode a data-readiness one. Picking a smaller weight would
    have been fitting a magic number to the tests, so it went last in the sort
    as a pure tiebreaker instead, where it only speaks when the quantitative
    signals are genuinely equal.
  - `tests/test_intelligence_ranking_signals.py`, 16 tests, **8 fail against the
    pre-fix source**. Deliberately split: the adjustment-maths tests pass both
    before and after (that function was always correct), so a separate class
    pins that `score_candidate` actually *calls* it — without which the whole
    fix could be reverted and everything else would still pass.
  - Subset went 9 failed / 11 passed → 7 failed / 13 passed, no regressions.

- **29 — cross-type duplicate candidates.** Every pick reached the board twice:
  once as the full candidate (~100 keys, `recommendation_id`, confidence as a
  `"38%"` string) and once as a reduced blotter/ranked row (~35 keys, no
  `recommendation_id`, no `line`, confidence as `38.0`).
  `_recommendation_sources` concatenates several response keys, so both landed
  in one list. **Two independent defects, and fixing either alone changed
  nothing** — which is why this survived so long:
  - The dedup key joined id/name/market parts with `if part`, dropping empty
    components instead of holding position, so the two shapes produced keys of
    different *arity* (`"<recid>|over 0.5|hitter home runs"` vs
    `"over 0.5|hitter home runs"`) and could never collide.
  - `_recommendation_sources` had two early returns handing back the raw list,
    skipping the dedup entirely whenever an upstream key was already populated
    — the common case.
  - **The generalisable rule: a field only ONE representation carries is
    unusable as a hard key component.** True of `recommendation_id`, and
    equally true of `line` — an intermediate fix that put `line` in the tuple
    failed identically (`'0.5'` vs `''`). `line` is now a wildcard: missing on
    either side still matches, two different lines still stay distinct.
  - The same broken key existed in **two copies** (`intelligence_board.py` and
    `pipeline/intelligence_state.py`); both now call one shared
    `dedupe_recommendation_items`, so they cannot drift apart again.
  - `tests/test_intelligence_board_dedupe.py`, 14 tests. Validated against both
    the original key and the intermediate line-in-tuple attempt: both return 2
    where the fix returns 1, so the guards are not vacuous.

- **58 — basketball quarter sim vectorised.** `_simulate_quarters_local` looped
  over samples in Python and, *inside* that, over the four quarters, rebuilding a
  2×2 covariance and running `np.linalg.cholesky` every iteration — ~20,000
  decompositions per game of a matrix that depends only on the quarter. Hoisted
  the covariance and its factor to once per quarter (4×) and replaced the scalar
  `size=(2,)` draws with one `size=(n_draws, 2)` batch per quarter, using
  `Z @ chol.T` for the batched form of `chol @ z`.
  **Measured 215.0 ms → 2.9 ms per game (73×)** at 5,000 samples / 4 quarters.
  - Hoisting the `try`/`except` from per-sample to per-quarter is equivalent
    *because the covariance is sample-invariant*: cholesky either succeeds for
    every sample of a quarter or fails for every one. That is the load-bearing
    argument for the refactor; if a future change makes the covariance vary
    within a quarter, this stops being safe.
  - **Draw order changed**, so a given global RNG state no longer yields the same
    numbers. Nothing depended on it: the function takes no `cfg` and no `rng`,
    never seeds, and the only test that referenced it patched it out entirely.
    Distributions verified equivalent against the pre-fix loop.
  - The fallback path still draws *independent* normals with **no clamping at
    zero**, unlike the correlated path which clamps. That asymmetry predates #58
    and was deliberately left alone — it is a real inconsistency if anyone ever
    hits it, but changing it would have been a behaviour change smuggled into a
    performance fix.
  - `tests/test_basketball_props_quarter_sim.py`, 9 tests. The four structural
    guards were **validated against the pre-fix source: all four fail there and
    pass on the fix**, so they are not vacuous. A distribution-only test would
    have passed against the slow version, which is why the guards count
    decompositions and draw shapes rather than checking moments.
  - ⚠️ **CPU only.** The accumulators went from two 5,000-float Python lists to
    two float64 arrays. Do not read this as progress on #59's memory question.

- **64 — Make the candidate pool's last stage visible** (`a1638c39`).
  *Recorded retroactively 2026-07-26: this shipped on 2026-07-25 and was never
  filed in either list — the only such gap in 200 commits. See #71.*
  Classification and dedupe were the last stage before the pool and the only one
  with no `INTEL_TRACE`; they reported through `_log_json_event` at
  `logging.INFO`, which never reaches Render's collector (#37). So the pipeline
  could discard every candidate and report `candidate_count=0` with no visible
  reason. Adds candidates-in, how many classification and dedupe each removed,
  and a **count per rejection reason**. Deliberately does **not** guess which
  rule fires — the remaining suspects are `missing_selection` and
  `missing_projection_or_odds`, and which one is a production fact to be read,
  not inferred. **The instrument shipped; the reading has not been taken.** That
  reading is the open work in #68.

- **17 — slate endpoint.** Core and segment payloads merge per bookmaker *before*
  `_best_bookmaker_game_lines` scores them; scoring separately would pick one
  book for core and another for segments and mix two books' prices into one
  game. Falls back to per-event on failure, but a fatal `OUT_OF_USAGE_CREDITS` /
  bad-key response **raises** instead — silently falling back to the
  15×-more-expensive path on running out of credits is the worst possible
  response. First tests this fetcher has ever had.

- **18 — NCAAF regions.** Real trade: NCAAF keeps every bookmaker the API returns
  with no US filter, so eu/uk books drop out of each game's provider list — the
  same set every other sport already lives without. `ODDS_API_REGIONS` still
  overrides, so reverting is an env change, not a deploy.

- **25 (Phase 0)** — *Atomic writes*: `atomic_artifact_write.py`, wired into 11
  call sites across 7 producers. `df.to_csv(path)` truncates then streams, so a
  reader arriving mid-write silently gets fewer rows — one of the candidate-swing
  symptoms. Temp files carry pid+uuid and sit in the destination directory.
  *Fail-closed launch marker*: `_record_odds_refresh_launch` moved to **before**
  `launch_refresh_run`; a raise after the spawn used to leave a sweep running
  with no marker and the next tick started a second one (#20). A missed refresh
  self-corrects; a duplicate burns credits and stacks two heavy pipelines. 16
  tests.

- **41 — scoped-resim regression coverage** (`dcda6243` shipped the fix untested).
  `tests/test_mlb_scoped_resim_summary.py`, 8 tests in two layers: a behavioural
  consumer contract on `_games_from_daily_summary`, plus a structural guard on
  the vendored producer — necessary because the fix lives inside a ~2000-line
  `main()` whose helpers are nested locals that cannot be imported. **Validated
  against `dcda6243^`: all five fail on the pre-fix source**, so they are not
  vacuous. If `daily_update.py` is re-vendored and the guards fail, check the
  merge is still present before loosening assertions.

- **14 — quota instrumentation.** Records observations rather than accumulating,
  because `used`/`remaining` are absolute server-side counters — so burn survives
  the lost writes from three services racing on a non-atomic store. Recorded
  *before* `raise_for_status`, since a failed call may still be billed. Reports
  `None` rather than `0` on a single observation: "not measured" must not look
  like "not burning". NCAAF/NCAAB reach the API through `urlopen` with the apiKey
  in the URL, so those record **only the path** — the endpoint is persisted to
  the shared store and must never carry a key.

- **44b — soccer resim, shipped dark.** Enable via
  `SYNDICATE_ENABLE_SOCCER_RESIM_TRIGGER=true` on live-odds-worker plus
  `SYNDICATE_SOCCER_RESIM_TICK_OWNER=false` on refresh-worker. ⚠️ It forces an
  odds refresh with cache bypass and soccer props are ~2,400 credits/sweep
  (#19) — keep dark until burn fits the 5M target.

## Closed 2026-07-26 / 07-27 — the empty-board session

The board went from serving 7 shell-command placeholders to **27 real MLB props
with prices, lines and edges** (`/api/intelligence/status` 2026-07-27T00:05:49Z,
`candidate_count: 27`, all from the one live game, correctly flagged live).
Five defects, in order of how load-bearing they were.

- **79 — the board build's memory guard counted reclaimable page cache.**
  `MEMORY_GUARD_ABORT` every cycle: `current 3228.3 / max 4096`,
  `headroom 867.7` against a 900 floor. But `anon` was **662.5 MB** and
  `inactive_file` **2476.3 MB** with `shmem 0.0` — real headroom was 3393.7 MB.
  Fixed to `max - (current - inactive_file - slab_reclaimable)` (`7b204998`),
  conservative on purpose (`active_file` and `shmem` still count as used) and
  falling back to the old calculation when `memory.stat` is unreadable.
  ⚠️ **This retired the "2.7 GB plateau" as page cache from the 1.24 GB
  odds-events file, not a leak** — which is why `tracemalloc` was blind to it.
  **#76 still leaves that file unbounded.** The gate is shared with
  `live_refresh_loop`'s odds-refresh gate and the MLB live-lens `estimate_live`
  gate, so both gained headroom too.
- **68a — a projection of exactly zero read as missing.** The presence test was
  `_safe_text(value, "") not in {"", "-"}` and `_safe_text` is truthiness-based.
  A live game-level candidate with no explicit `live_projection` gets the game's
  combined score, which is **0 for every scoreless live game**, and that 0 also
  shadowed the real `model_probability` behind it. Fixed with
  `_candidate_value_is_present`.
- **68b — `shared_top_play_rows` published a display panel as picks.** 56 rows
  per MLS slate reading "Projected score: …", "Margin: 0.80 (home perspective)"
  and literally **"Simulations: 400"**. Gated on the row expressing a side
  (over/under) or carrying a scraped price/edge. ⚠️ Only 68a's bug was keeping
  these off the board — fixing 68a alone would have published all 56.
- **77 — placeholders and false liveness.** (a) `_unsimulated_game` empty states
  reached the board as LIVE picks whose `pick` was a shell command; gated at the
  producer on an explicit marker (`70ad2c9f`). (b) **Reported by the user:**
  yesterday's finished MLS fixtures flagged live. The payload contradicted
  itself — `shared_is_live: true` beside
  `shared_game_state {"live": false, …}` — and soccer's `status` is a display
  string so neither the `status` dict nor `live_state` was populated. Structured
  state now wins (`1b333736`), scoped so `shared_is_live` still decides when
  nothing contradicts it.
- **78 — WITHDRAWN, not a date-selection defect.** Every cycle builds TODAY and
  *then* probes tomorrow; the probe emits its own dated traces, so a tail of the
  logs shows only the tomorrow half. Misread into three investigations
  (#65, #68, #78). `ROLLOVER_PROBE_BEGIN`/`END` and dated
  `CANDIDATE_POOL_READY` now make the two halves unambiguous.
- **65 — MISDIAGNOSED, kept as the worked example.** The rollover probe is
  expected behaviour, not a queued future-dated payload; the two guards shipped
  against the queue path never fired because the queue was never involved.
- **66 — board shows no opportunities.** Superseded: the live-slate reading it
  asked for was taken (100% pruned at classification) and the causes are 68a/68b
  above.
- **75 — refresh-worker OOM at 4 GiB.** `_load_jsonl_rows` slurped a 1.24 GB
  odds file before applying its row cap; streamed into a `deque(maxlen=N)`
  (`5181ed3d`), 734.6 MB → 2.9 MB peak.
- **43 — Layer 2 curated board empty.** ✅ **Closure criterion finally met:**
  `candidate_count: 27` **with** `snapshot_generated_at 2026-07-27T00:05:49Z`.
  The transport work (`e323d61f`, `31ff3438`, `81475c19`) is deployed on web and
  worker. ⚠️ **Still unexercised at size** — no cycle since has produced a pool
  large enough to divert to the artifact transport, so the oversized-payload
  path remains deployed-but-unproven. If a big slate ever fails to publish,
  start there rather than assuming it works.
- **71 — nothing checks that shipped work reaches this list.** Audited across
  200 commits: #64 was the only instance, so it is rare rather than systemic.
  The check now lives in Operational notes and was run for this reconciliation
  (30 IDs across 80 commits, all present).

- **80 — admin-token rotation.** Removed from the list at the user's request
  2026-07-27. ID retired, not reused.

- **72 — the per-query prediction-ledger write, deleted 2026-07-27**
  (`569c4e9f`). `record_prediction` ran for every recommendation of every
  intelligence query and rewrote the whole multi-MB
  `data/prediction_ledger.json` on the request path, while its only automated
  reader reported `prediction_ledger_count: 0`. Removed on the user's decision
  that the ledger is obsolete. **Kept:** the `/api/portfolio/bets` write (user
  bets, genuinely read by `/portfolio`) and portfolio_summary's stake-presence
  check (old ledgers still carry stakeless auto-rows). Also deleted the test
  fixture that existed solely to patch this write out — it was 1.46s of a 2.6s
  test. Verified post-deploy: board rebuilt fresh (`01:49:46Z`, 27 candidates).

- **76 —**🟢 **RESOLVED 2026-07-27T01:11Z — verified by file size, not by log line.** `odds_events/<date>.jsonl` grew unbounded (1.24 GB → 1.71 GB in one day); nothing read past the last 2000 rows (`_load_jsonl_rows` deque cap, sole production reader), so it was pure dead weight filling the page cache #79 measured. **Fix, three commits:** append-path compaction to the last 20k raw lines (`0508f8bd`) with a **growth-based** trigger — an absolute ceiling compacted on *every* append once retained > ceiling, 300 compactions/80k rows measured locally, caught before ship; a stale-file scan for closed days (`ec256961`); and the scan triggered from the **read** path too (`3d2110e3`) — production showed refresh-worker holds the 2.66 GB backlog but never appends (odds refresh appends on live-odds-worker), so an append-only hook would never have run on the box that needed it. **Verified in production:** `2026-07-26.jsonl` **1,712,508,566 → 39,296,335 bytes**; `07-24` (315.7 MB) and `07-25` (512.5 MB) stopped printing `ODDS_JSONL_LARGE` entirely (threshold 8 MB), so both trimmed; the `COMPACTED` prints themselves never surfaced (subprocess stdout / spotty logs API) — **the sizes are the evidence**. Residual by design: `07-21/22/23` (46.7/56.9/16.5 MB) sit **below the 64 MB trigger** and are left alone; ~120 MB total, ages out within a week. Footprint ~2.66 GB → ~175 MB. ⚠️ Read-then-replace race documented in the code: fine for tail-read telemetry, needs a lock if a second writer or system-of-record use ever appears. `SYNDICATE_ODDS_EVENTS_COMPACT_BYTES=0` disables.

- **45 — WNBA All-Star game missing from the market board.** Overtaken by
  events 2026-07-26: the game has been played. Closed without a fix at the
  user's direction; if the same gap matters for a future special-event game,
  file it fresh against that game.

- **70 — render.yaml comments contradicted their values.** Closed 2026-07-27 on
  inspection: the comments were **already corrected** in `5b89aef3` (2026-07-26,
  the same reconciliation commit that filed the item) — both intelligence-loop
  blocks now tell the accurate post-#57 story and match their values. The open
  row outlived its own fix by a day; nobody re-checked the file before carrying
  the item forward. Verified directly against render.yaml lines ~318–330 and
  ~550–562 before closing.

- **81 — execution guard released in a `finally`** (`b9da4979`, 2026-07-27).
  Filed and fixed the same night: the release was a plain statement after the
  persist, so 01:04Z's thread death kept the guard held and the MLB sim
  deferred forever against a dead pipeline. The whole acquisition-to-wait
  stretch now runs under a finally; a thread-level test injects a failure into
  exactly the stretch that killed the production thread and asserts the guard
  unlocks even though the thread dies. Verified live: first post-deploy cycle
  built and persisted clean.
- **#29 follow-on — cross-source market synonyms** (`23fcf8fc`, 2026-07-27).
  User-reported: "Tyler Phillips outs is listed twice from two sources." The
  "Pitcher top props" rail (`outs recorded` / `Over 15+`) and the props
  artifacts (`pitcher outs` / `OVER Tyler Phillips`) spell the same bet
  differently, and #29's raw-string core could never collide them. Dedupe key
  now canonicalizes market (role prefix stripped + synonyms) and collapses
  selection to its side token — only when a player subject exists, so game
  markets are untouched. Verified against the live board pre-deploy (38→35,
  exactly the three reported twins) and post-deploy (`board_cards: 35`).
  ⚠️ Lesson: **an automated "no duplicates" check that shares the dedupe's key
  is blind to exactly what the dedupe misses** — a user looking at the actual
  board caught what instrumentation could not. Residual: the candidate POOL
  still carries both shapes (`candidate_count: 38` vs 35 cards); folding the
  canonical key into the pool merge is a small cleanup.

- **87 — event-sim rerun decision always forced a rerun** (2026-07-27). The call
  site at [unified_daily_update.ps1:4619](../../scripts/unified_daily_update.ps1)
  passed `-ArtifactPath [string]$eventPlan.artifactPath` — in PowerShell argument
  mode an un-parenthesized `[type]` before a value is not a cast, it is literal
  text, so the argument was actually `"[string]" + $eventPlan.ToString() +
  ".artifactPath"`, a path that can never exist. `Test-Path` inside
  `Get-EventSimExecutionDecision` (line 2040) therefore always returned false and
  forced `$true`, permanently defeating the fingerprint-equality skip four lines
  below it (line 2052) — the event sim reran every tick regardless of whether its
  inputs had changed. User caught this by reasoning through the parser, not from
  observed behavior. Fixed by parenthesizing: `-ArtifactPath
  ([string]$eventPlan.artifactPath)`. Repro'd the parse bug directly
  (`Test-Arg -ArtifactPath [string]$eventPlan.artifactPath` prints the literal
  `[string]@{...}.artifactPath` text) before and after the fix. Added
  `UnifiedDailyUpdateEventSimDecisionBehaviorTests` to
  `tests/test_unified_daily_update_event_sim_freshness_window.py`, which actually
  invokes the extracted PowerShell function via `powershell.exe -ExecutionPolicy
  Bypass` rather than only pinning source text. ⚠️ **Verified by reverting the
  fix that only the string-pin test catches this exact regression** — the
  behavioral tests construct their own arguments and exercise the function
  correctly regardless of what the buggy call site does, so they pass either way.
  A call-site argument-parsing bug like this one needs a source-text assertion,
  not (only) a functional test of the callee.

- **88 — two production bugs in `refresh_ncaaf_oddsapi.py` from `ce48b4de`
  ("Allow local NCAAF artifact refresh", 2026-05-22)** (2026-07-27). Both were
  in code that had apparently never run end to end since that commit.
  - **(a) `_base_norm` was mangled.** Its body was a copy-pasted fragment of
    `_copy_tree_if_exists` (referencing undefined `source`/`destination`) that
    fell through to `return ""` for every team name; the real normalization
    tail had been left as dead code *after* `_resolve_data_root`'s
    `raise FileNotFoundError`. Every team name normalized to the empty string,
    so `_norm_team`/`_best_schedule_norm` could never match an odds row to a
    schedule row on a real refresh. Fixed by restoring `_base_norm`'s body and
    deleting the dead fragment; also dropped a redundant literal-filename
    `.exists()` check in `_resolve_data_root` that duplicated the glob check
    beneath it and could never match a real (timestamped) filename anyway.
  - **(b) artifact-root-only mode crashed.** `_prediction_files` always looked
    under `<root>/data`, but `scripts/refresh_odds_sources.py`'s NCAAF step
    (the actual production caller) invokes the runner with `--artifact-root`
    only, and that bundle stores
    `college_football_schedule_*_predicted_totals_enhanced*.csv` at the bundle
    **top level**, not under a `data/` subdirectory — so every orchestrator run
    raised `FileNotFoundError` before reaching the OddsAPI call. Verified
    against the real bundle
    (`data/ncaaf_source/source_artifacts/college_football_schedule_2025_predicted_totals_enhanced_*.csv`
    sits at top level, confirmed with `ls`). Fixed `_prediction_files` to try
    `<root>/data` then fall back to `<root>` directly, so both the
    `--source-root` (nested) and `--artifact-root`-only (flat) layouts resolve.
    Reproduced the exact orchestrator invocation
    (`--artifact-root data/ncaaf_source/source_artifacts --week 7`) before and
    after: before, `FileNotFoundError`; after, it reaches the live OddsAPI
    request (fails only on an invalid dummy key, as expected).
  - The existing test (`test_main_uses_artifact_root_as_data_root_when_source_root_omitted`)
    was silently papering over (b) by creating the CSV in **both** locations;
    simplified to only the flat layout now that the runner handles it. Added
    two direct regression tests for `_prediction_files`/`_prediction_context`
    (flat and nested layouts) and one for `_base_norm`/`_norm_team`. All 192
    NCAAF-tagged tests pass (`python -m pytest tests/ -k ncaaf`).
  - ⚠️ **Not yet observed fixed against a live OddsAPI key in production** —
    verification here was local (real bundle files, dummy key, and unit
    tests). Confirm the orchestrator's `ncaaf_lines_snapshot` step actually
    writes updated lines on its next real run before considering NCAAF fully
    healthy again.
  - Both #87 and #88 were marked closed here while their fixes still sat
    uncommitted. Neither reached `main` until a later session (2026-07-27)
    ran `git commit`/`git push` on request, landing in commit `0250ac82`
    alongside #74's fix and the undocumented #91 batch. See the Operational
    note in `todo.md` about the inverse of #71: a closed doc entry does not
    mean the code shipped to git.

- **89 — `migration_gate.py`'s `evaluate_protected_local_resolvers()` was
  stale against `757952e1`** ("Refactor WNBA odds path resolution",
  2026-06-28) (2026-07-27). That commit routed NBA's `processed_path` and
  NHL's `processed_path`/`scoreboard_snapshot_path`/`slate_summaries` through
  the new `odds_control_plane.current_odds_root_for_sport`, which imports
  `preferred_source_roots` in `odds_control_plane.py` itself — not the
  binding in `nba.sources` or `nhl.sources` that the gate was patching. So the
  gate's mocks silently stopped taking effect and it **unconditionally
  reported 3 violations** (`runtime_dependency_ok` permanently `False`,
  failing `tests/test_migration_gate.py::MigrationGateRuntimeDependencyTests::test_evaluate_protected_local_resolvers_passes_current_contracts`).
  - **NHL fix was mechanical.** `_data_roots()` always resolved to a single
    root even before the refactor (`_source_roots()[0] / "data"`), so the
    gate's expected values (local mirror, never the sibling bundle) were
    already right — only the patch target moved, to
    `syndicate.features.nhl.sources._data_roots` directly (matching the
    already-public wrapper the module exposes, rather than reaching into
    `odds_control_plane`'s internals).
  - **NBA is a real contract change, confirmed against the diff, not just a
    stale mock.** `757952e1` deleted the `_first_existing_path` fallback scan
    from `processed_path`/`live_snapshot_path`; NBA no longer picks whichever
    preferred root actually has the file — it always resolves to the primary
    root now, matching NFL/NCAAF's existing "stays on local mirror, no
    sibling-app fallback" pattern and the codebase's stated direction away
    from source-app fallback dependencies. Updated the gate's expectation to
    match (`local_root`, not the external bundle) and patched
    `nba.sources.artifact_processed_root` directly, alongside the existing
    `nba.sources.preferred_source_roots` patch (the latter still governs
    `available_dates()`, which is unaffected by this refactor). This mirrors
    the patch convention other pending test fixes in the same working tree
    (`tests/test_nba_live_snapshots_local.py`, `tests/test_nba_refresh_runner.py`)
    had already converged on for the same `757952e1` gap — same root cause,
    caught independently in two places.
  - Verified: `python -m pytest tests/test_migration_gate.py -q` → 16 passed;
    `evaluate_protected_local_resolvers()` also returns `[]` against the real
    (unpatched) environment.
  - ⚠️ **Surfaced a real, separate latent inconsistency, filed open as #90**:
    NBA's `available_dates()` was left scanning all preferred artifact roots
    while `processed_path()` now only resolves the primary one — dormant
    today because production has one NBA root, but a foot-gun the moment a
    second one exists.

---

## Closed earlier

- **1** sim fast-path runtime ceiling · **2** memoize `build_reliability_profile` ·
  **3** deploy+restart for stuck 7-25 sim · **4** last-known-good board while stale ·
  **5** mini card live scoreboard · **6** last odds refresh + sim run on cards ·
  **7** Layer 2 blotter fixes · **9–11** odds-history Phases 1–3 · **13**
  per-candidate live-state cache defeat
- **8** Empty production board (the `NameError`). ⚠️ *The fix was correct, but the
  same symptom recurred 2026-07-25 via an unrelated cause (#43). "Empty board" is
  a symptom with at least two distinct root causes — do not treat it as a solved
  class.* (This warning is also carried in `todo.md`'s Operational notes, because
  it is still live.)

---

## Recovered 2026-08-09 by the list audit — shipped 08-05/08-06, never recorded anywhere

These six IDs appeared in commit subjects and in **neither** `todo.md` nor this
file, found by running the `#71` check across every commit since 2026-08-05.
They are one coherent workstream — retiring "infer a wager from display text" —
and it finished. Recorded here for the record; nothing outstanding.

The lesson that *is* still live was promoted to `todo.md`: **a counter built
before the fixes is what located them.** Three changes that day passed their
tests and did nothing in production, and a later three-line change moved
`top_props` from 0-of-14 priced to 12-of-14 — an effect invisible for as long as
it existed because nothing counted it.

- **#222/#223** (`1f6c27b9`) — `opportunity_contract_metrics`: count, per sport
  and per lane, how many rows arrive without a canonical `market_key`, an
  `entity_name` for props, or an event identity. Instrumented at three points,
  deliberately including the prop source *going in* to `_finalize_home_prop_rows`
  so the numbers describe what producers emit rather than what that function
  patched up. Served at `/api/ops/opportunity-contract/status`. **Sequenced
  before the fixes on purpose.**
- **#225** (`5dd3632d`) — closed the four gaps the counter named, each located
  rather than guessed: four more prop builders carry a canonical key
  (`_prop_rows_from_nhl_cards`, `_prop_rows_from_mlb_live_games`,
  `_prop_rows_from_nba_live_lens`, `_prop_rows_from_props_recommendations_csv`).
  **The counter also lied about itself** — `prop_dashboard_row` was recorded
  *before* `enrich_prop_rows` ran, so `quoted` read 0 while the same build served
  priced rows.
- **#227** (`fc63965a`) — MLB HR targets carried **no `market` key at all** and
  set only `name`, never `player_name`: every HR-target row was both keyless and
  entity-less to the contract. Market fixed rather than derived
  (`batter_home_runs`), because deriving it from a label would introduce a guess
  where a certainty exists. `line` deliberately stays `"-"` — "support" is a
  model confidence score, not a betting line.
- **#228** (`b8c93bc7`) — the last 2 of 18 WNBA keyless prop rows: blocks,
  steals, turnovers, double-double were missing from the basketball map. ⚠️
  **Filled from the feed's vocabulary, NOT confirmed against those two rows** —
  web began 502-ing under the repeated dashboard rebuilds being used to force
  fresh counters, and a two-row lookup was not worth destabilising it. Inferred,
  and said so.
- **#229** (`ed10dc9b`) — rails stop being a data source. `home_rails` is a
  *presentation* shape, and three consumers were reading
  `home_rails["pregame"]["items"]` as the opportunity feed. The overview now
  publishes `prop_opportunities` under its own name. Covers all four read sites
  including the `live` lane at `intelligence.py:7201` that a first pass missed.
- **#230** (`3bfba211`) — deleted the prose scraper, the last place the codebase
  inferred a wager from display text. `_game_bet_candidates_from_game`
  regex-scraped candidates out of a human-readable panel, producing 32 MLS
  "candidates" reading *"Projected score: New England Revolution 1.4 - CF
  Montreal 2.1"* and literally *"Simulations: 400"* — surviving only because a
  truthiness bug happened to prune them.


## Archived 2026-08-10 — soccer sim concurrency lane

`#282` and `#311` below are closed and verified in production. **`#312` was
deliberately NOT archived** — its protection is on `main` and live on no
service, and the blueprint-sync mechanism remains untested.

Per this file's own rule, the lessons that should still change behaviour were
left in `todo.md`: the residual (the fault is bounded, not removed, and the
bound is a cap of 1 that is unset in config) and the four-times-repeated
null-anchoring error. Read the lane summary at the top of `todo.md`, not this.

## #282 — CLOSED 2026-08-10, deployed and VERIFIED in production across a full rotation. Soccer sim split into per-league-date jobs. And the premise the brief was written on was false: soccer sims were never off

**VERIFIED 2026-08-10 on refresh-worker. The round-robin completes a full
rotation and then repeats — every unit ran, none starved:**

```
2026-08-09 23:12:18Z  eredivisie          08-09   unit=1/4  due=4   spacing 3600
2026-08-10 00:12:33Z  primeira_liga       08-09   unit=1/4  due=3   spacing 3600
2026-08-10 01:27:01Z  primeira_liga       08-10   unit=1/4  due=2   spacing 3600
2026-08-10 02:27:21Z  belgian_pro_league  08-09   unit=1/4  due=1   spacing 3600  <- rotation complete
2026-08-10 03:28:00Z  eredivisie          08-09   unit=1/4  due=1   spacing 3600  <- second cycle
2026-08-10 04:28:06Z  primeira_liga       08-09   unit=1/4  due=1   spacing 3600
2026-08-10 08:28:17Z  primeira_liga       08-10   unit=1/1  due=1   spacing 14400 <- date rolled, 1 unit
2026-08-10 12:28:30Z  primeira_liga       08-10   unit=1/1  due=1   spacing 14400
```

`due` counts **4 → 3 → 2 → 1** as each unit is stamped, then units age past the
4h interval and the cycle repeats. All four units the resolver predicted locally
ran in production, and the observed spacing (~1h with 4 units, 4h with 1) is
`interval // unit_count` exactly. **One league, one date, per job — eight times.**
Under the old code those eight would have been eight whole-sport jobs of 10–20
minutes each.

#### THREE separate people read this wrong, all by choosing a start time

This is the reusable part, and it cost more than the feature did.

- **Me, first:** watched 15 minutes from the 03:46:11Z boot, saw nothing,
  and began building instrumentation for a silent-gate hypothesis.
- **Me, second:** anchored a probe on that same 03:46 boot — but `fd119e17` was
  already live on `ef3f6a2b` (03:32Z) and had been *running since 23:12Z the
  previous evening*. The probe could not see five of the eight launches.
- **The `#319` lane:** searched from the deploy and concluded "all three
  launches are `primeira_liga`", reasonably suspecting the scheduler only ever
  picked one league. Their window opened *after* the first rotation had already
  covered all four.

Every one of those readings was internally consistent and wrong, for the same
reason: **a log window that starts after the interesting part renders "it only
does X" and "it does nothing" identically to "it already did everything".** The
fix is not a better instrument, it is anchoring the window on **when the code
could first have run** — `git log -1 --format=%cI <commit>` — not on the deploy
you happen to be watching. `fd119e17` was committed 21:20Z; every window that
started later was guessing.

**Corollary, since I nearly shipped a fix for a non-bug:** `due=1` on an
early launch looked anomalous against a 4-unit list and was the tail of a
countdown. Had I not widened the window, I would have "fixed" a working
scheduler.

#### The instrumentation gap is real, but it was NOT this

Three of the autorun's return paths (spacing, active job, nothing due) emitted
nothing, so from outside I could not distinguish them. That is a genuine hole
and it is closed —
`SOCCER_AUTORUN_SKIPPED reason=<spacing_gate|active_job|no_unit_due>`, printed
**on reason CHANGE, not per tick** (the detail carries counters that move every
cycle, so keying dedup on reason+detail would print every 30s forever; written
and caught before shipping).

But it is closed **on its own merits, not as a fix for this**, because this was
never a silent-gate failure. `"the window was too short" is also what an inert
deploy looks like` remains a sound rule — what it needed was not more logging
but the discriminator already in the payload: **`spacing_seconds=14400` names
the cadence, so the required window was knowable in advance.**
[[read the field you already have]]

> **ATTRIBUTION CORRECTION + AN ORPHANED FINDING, added by the coordinator
> 2026-08-09 ~21:3xZ.** I credited `de1a6906` and `50afe2ae` to the `#282` lane.
> **They are not its commits.** Every lane commits as `github-actions[bot]`, so
> the author field distinguishes nothing — an assumption worth retiring
> permanently, because it will mislead again.
>
> Those two belong to a different, unidentified soccer lane, and their content is
> **not** folded into `#282` and is not recorded anywhere else. Placing it here
> so it survives:
>
> - **All 10 soccer leagues ARE active**, so the chip gap is **per-league
>   artifact availability**, not league coverage (`50afe2ae`, 13:11Z).
> - **Soccer week resolution is refuted** as the cause; narrowed to per-league
>   card artifacts (`de1a6906`, 13:23Z).
>
> Two hypotheses killed, which is what makes the next attempt cheap. **Unowned.**
> Do not re-derive them, and do not attribute them to `#282`'s lane.

**The deliverable, in one line:** one soccer job used to be all ten leagues
(~10–20 minutes of real work); it is now one league on one date. `--soccer-leagues`
and `--soccer-date` on `refresh_odds_sources.py`, plumbed through
`launch_refresh_run`, with `_launch_autorun_soccer_weekly_refresh` picking one
unit per launch, stalest-first, spread across the same 4h interval.

**THIS BOUNDS THE DAMAGE. IT DOES NOT REMOVE THE DEFECT.** There is still no
concurrency guard in the claim path. An unterminated claim loop still grows
without limit — just more slowly, from a lower base, with more headroom to
notice. See `#279`'s "a real concurrency bound in the claim path", still
unowned, and the two findings below that make it worse than it reads.

#### FIRST: "soccer sims are OFF by standing instruction" was not true

I was briefed that soccer was running degraded with sims disabled until this
landed. Three independent reads say otherwise, and the lead has since confirmed
the instruction was never applied:

- **Live env on refresh-worker:** `SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_AUTORUN
  = 'true'`, `..._INTERVAL_SECONDS = '14400'` (queried the env-vars API, 94 keys).
- **The live deploy contains all three soccer sim fixes.** refresh-worker was on
  `27a7e9df`; `git merge-base --is-ancestor` puts `c9fbb736`, `a03c2cfb` and
  `16c26e5f` all inside it. So the pre-incident "sims die in 2s, retries are
  harmless no-ops" state did not apply.
- **A sim actually ran**, 17:56:36Z → 18:16:49Z on 2026-08-09.

**Nothing was mitigating this all evening.** The configuration that produced nine
OOM kills was the configuration running. It did not recur — max concurrent
soccer sims was **1 across 1200 samples** — so the amplification is latent, not
live, but nobody was holding it back. [[instrument blindness]]

#### The measurement, and the correction to the arithmetic that justified this item

`STEP_END` never reaches Render's log collector — `run_refresh_odds_job.py:619`
runs the orchestrator with `stdout=PIPE, stderr=PIPE` and writes both to files.
That absence is legitimate, not a lost signal, and it is why this was measured
off `ALL_PROCESS_MEMORY`'s per-process `cmdline` lists instead. Eight
consecutive whole-sport jobs on refresh-worker:

```
job start   eredivisie  primeira_liga  belgian_pro_league   whole job
01:55Z         596s          315s            340s            1391s
04:45Z         332s          322s            363s            1154s
05:55Z         179s          251s            187s             660s
08:04Z         182s          168s            209s             603s
09:03Z         146s          211s            216s             616s
09:56Z         155s          203s            234s             628s
13:56Z         147s          191s            228s             606s
17:56Z         311s          431s            390s            1213s
```

The other seven in-season leagues exit in ~0s — `16c26e5f`'s horizon bound
leaves them nothing inside today+1 to simulate.

**THE BRIEF'S ~6x IS WRONG. THE REAL FIGURE IS ~2.8–2.9x, and the reason is the
part worth keeping:** concurrency after the split is set by the **longest single
unit**, not the average one. Three leagues do essentially all the work, so
splitting ten ways buys `616/216 ≈ 2.9x` on the median job and `1213/431 ≈ 2.8x`
on the worst observed one. An equal-league-dates model predicts 6x and a
count-the-leagues model predicts 10x; both are wrong for the same reason, which
is that they average over a distribution whose maximum is what matters.

At the live 30s poll interval, a wedged claim goes from ~20 concurrent jobs
(median) / ~40 (worst) to ~7 / ~20, each holding one league instead of ten.

#### Write volume — the thing this could have quietly made worse

More, smaller jobs means more launches on a path already implicated in write
pressure, so this was measured rather than argued:

- **Launches per 4h interval go from 1 to 4.** Not 10 — the unit resolver returns
  **4 units** for 2026-08-09 (`belgian_pro_league` ×1, `eredivisie` ×1,
  `primeira_liga` ×2 dates). Those are exactly the three leagues that did real
  sim work in production, which is an independent check that the resolver
  matches reality rather than the local mirror.
- **5 state writes per launch, in-process, measured:** 3 in the
  `launch_refresh_run` enqueue (`refresh_status_manifest`,
  `refresh_status_latest`, `refresh_and_gate_run`) + 2 in the launcher
  (autorun status, worker status). The claim/execute writes downstream are
  unchanged per job — this adds none — they just happen 4× instead of 1×.
- **Denominator:** refresh-worker already emits **794 `PUBLISH_OK`/hour**
  (measured, 2h window). The added state writes are ~13/hour. Different write
  paths, so that is a scale reference and not a like-for-like ratio — but the
  cost is not close to the benefit's order of magnitude.
- Idle ticks write nothing: the loop's only unconditional `_write_worker_status`
  is behind `elif args.run_once`, which never fires in the long-running worker.

#### Composition with `16c26e5f`, which was the stated risk

`--soccer-date` short-circuits `_soccer_artifact_scope_args` before it resolves
the matchweek, so a pinned unit emits `--date` and **not** `--week`/`--horizon-days`.
Test `test_pinned_date_scopes_the_sim_to_one_date_and_drops_week_scope` asserts
the absence, because reintroducing week scope per league is the exact
regression that would undo `16c26e5f` while looking like a working split.

#### Design decisions that are not obvious from the diff

- **Spacing gate, separate from the per-unit interval.** The interval decides
  whether a unit is *due*; spacing decides whether it is *this tick's turn*
  (default `interval // unit_count`). Without it, the first tick after a deploy
  finds every unit stale and fires them on consecutive 30s ticks — rebuilding
  the overlap this exists to prevent, by design rather than by accident.
- **A failed launch still stamps its unit epoch.** Otherwise a permanently
  failing unit stays the stalest forever, stalest-first returns it every window,
  and nothing else ever runs. A starvation bug that only appears once something
  is already broken.
- **Unresolvable schedule degrades to league-only scope, never to whole-sport.**
  Worst case keeps the bound.
- **Unknown league slug raises `SystemExit`** rather than building zero steps,
  and out-of-season leagues emit `SOCCER_LEAGUE_SCOPE ... skipped_out_of_season=`.
  Three different zeros — unknown slug, out of season, nothing in horizon — that
  previously all rendered as an empty step list. [[unknown must not default permissive]]

#### Two findings handed off, both unowned, NEITHER FIXED HERE

**A. The active-jobs cap cannot fire, for two independent reasons.**
`run_refresh_worker.py:1879` computes `active_jobs >= max_active_jobs`, writes a
`throttled` status, and then `return`s **only if `--run-once`**. The
long-running loop has no `continue`, so it falls through and spawns anyway.
And even with a `continue` it could not help: `_current_active_job_count`
returns 0 when the manifest is `running` with no live pid, which is *exactly*
the condition `_has_pending_external_contract` requires to re-claim. The two
predicates are mutually exclusive by construction — the cap reads zero
precisely when the runaway is running.
`SYNDICATE_REFRESH_WORKER_MAX_ACTIVE_JOBS` is unset on both workers, so it
defaults to 1: a limit of 1 that cannot be reached and would not be honoured.

**B. `render.yaml:532` hardcodes `SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_AUTORUN:
"true"`.** Turning soccer off through the single-key env API is therefore
undone by the next blueprint sync from any lane. Same class as `#284`/`#278`.

#### Deploy readiness

Committed, **not deployed**, no production change made — every Render call in
this lane was a GET. Code-only, so a push does not ship it; it needs an explicit
deploy of refresh-worker. **Deploying kills an in-flight sim**, and a soccer job
is up to ~20 minutes, so check before triggering one.

Tests: `tests/test_refresh_worker.py` + `tests/test_refresh_odds_sources.py` +
`tests/test_refresh_queue_runner.py`, **91 passed**. Seven of those are new and
named for the failure they prevent, not the feature they cover.



## #311 — CLOSED 2026-08-10, deployed and VERIFIED in production: the cap fired for the first time in this system's history at 16:06:31Z. It had been inert for two independent reasons, and the second one is the interesting one

**STATUS 2026-08-09, owned and fixed by the `#282` lane.** Both halves are
addressed in `235a868b`.

**Tests now RUN — gate met.** `pytest tests/test_refresh_worker.py -k "311"` →
**5 passed, 44 deselected**; the whole file → **49 passed**. Run by the
oversight lane after this entry first went in saying they had not been.

**How that gate was met is the part worth keeping.** The oversight lane had
already run the full file before committing and reported "49 worker tests pass"
*without checking whether these five were among them*. They were, and they
pass — **but the gate was met by accident**, and a passing aggregate that
happens to contain your tests is not evidence that your tests ran. Stating it as
blocking is what turned an accident into a check. [[a rate, not a count]]

**THE REMAINING CAUTION IS NOT A TEST CAUTION, AND PASSING TESTS DO NOT
DISCHARGE IT.** This cap has never once fired in production. **The pre-fix cap
passed tests too** — it was inert for reasons no unit test was looking at.
Judge it on real `JOB_CAP_THROTTLED` / `JOB_COUNT_DISAGREEMENT` lines after a
deploy, not on a green suite.

- **Half one — the cap was computed and then ignored.** It was a bare `if`
  followed by a separate `if _has_pending_external_contract(...)`, and the
  throttle branch `return`ed only under `--run-once`. Fixed by making the cap
  the **leading branch of the existing `if/elif` chain**, so at cap nothing else
  in the cycle runs and control reaches the poll sleep. **Note for anyone
  reading the diff: this is NOT a `+continue`.** The five `+continue` lines in
  that diff are loop control inside the new process enumerator. Judging the
  behaviour change by grepping for `continue` will find the wrong lines.
- **Half two — the cap could not have fired anyway.** New
  `_running_job_process_count()` counts live `run_queued_refresh_job.py`
  processes (one per claim, so counting processes counts running claims), and
  `_resolve_active_job_count()` returns `(count, source)` taking the **maximum**
  of the process and manifest counts. Max, not replacement, because the two
  fail in opposite directions: the manifest misses a job whose pid it never
  recorded, enumeration misses a job claimed but not yet spawned. Either alone
  reads low, and low is the direction that spawns.
- **Unknown is not zero.** Enumeration failure returns `None`, and the resolver
  reports `source="manifest_only_process_enum_unavailable"` rather than
  presenting the manifest's zero as verified. [[unknown must not default permissive]]
- A persistent manifest/process disagreement now emits `JOB_COUNT_DISAGREEMENT`,
  which was previously invisible. **See the correction below before trusting
  that marker — as first shipped it was mostly noise.**

#### CORRECTION 2026-08-10, found by watching the deploy rather than by review

**Both halves of `#311` work, and the cap fired for the first time in this
system's history** — `JOB_CAP_THROTTLED active=1 max=1 source=process_and_manifest`,
14:03:42Z, correctly, with a real job running. But the process counter was
**counting the wrong process**, and that had one benign consequence and one
that would have cost an incident.

It counted `run_queued_refresh_job.py`. Only the **queued-contract** path uses
that; the **autorun** path (`launch_refresh_run(launch_mode="web_process")`)
spawns `run_refresh_odds_job.py` directly. Measured on refresh-worker over 1.5h:

```
run_queued_refresh_job.py     0 samples with >=1
run_refresh_odds_job.py      33 samples with >=1   (max concurrent 1)
14:03:46Z peak sample: queued=0  odds_job=1  refresh_odds_sources=2
```

- **Benign:** the cap was still *correct*, because `max(process, manifest)` fell
  back to the manifest and the manifest happened to be right. The design
  survived the bug — which is the argument for `max()` rather than replacement,
  now demonstrated rather than asserted.
- **NOT benign:** `JOB_COUNT_DISAGREEMENT manifest=1 processes=0` fired on
  **every ordinary autorun job.** A marker this entry documented as "the
  wedged-manifest signature" was firing constantly during healthy operation.
  **A signal that cries wolf in normal operation is worse than no signal**,
  because at the moment you need it, it is indistinguishable from the noise it
  has been making all day. I introduced that.
- **Also not benign:** for the autorun path — the *common* path on this worker —
  the cap was still manifest-only, so the hole `#311` exists to close was open
  for the majority of jobs. It was closed only for the queued path, which is
  the one `#279`'s runaway actually used.

Fixed by counting `run_refresh_odds_job.py`, the one process both launch paths
have in common, **exactly once per job**. Not `refresh_odds_sources.py`:
`run_refresh_odds_job.py` carries it as a trailing argument, so that string
matches twice per job.

**The method note.** This was not findable by re-reading the diff — the code
does exactly what it says. It took watching production and asking why a marker
was firing when nothing was wrong. [[test the fix's predicate]]

**THE CAVEAT, AND IT IS THE REASON THIS SAYS "NOT RUN".** The five pytest tests
added alongside this have **not been executed** — the user declined the test
runs and I did not force them. What *was* run is a direct four-call functional
check of the new functions, and it passed:

```
_running_job_process_count() -> 0 (int)
wedged manifest: _current_active_job_count=0  _has_pending_external_contract=True
JOB_COUNT_DISAGREEMENT manifest=0 processes=3 using=3
_resolve_active_job_count -> count=3 source='process_and_manifest'
enumeration unavailable -> count=0 source='manifest_only_process_enum_unavailable'
```

That confirms the resolver behaves correctly on the exact wedged-manifest state
that caused the incident. It does **not** cover the `main()` loop restructure,
which is the half that changes worker behaviour on the next deploy. **Run
`pytest tests/test_refresh_worker.py -k "311"` before deploying refresh-worker.**

**This cap changes behaviour on the next worker deploy**, and
`SYNDICATE_REFRESH_WORKER_MAX_ACTIVE_JOBS` is unset on both workers, so it
defaults to **1**. A cap of 1 that now actually fires means a second concurrent
job is refused where previously it was spawned. That is the intent, but it
should be judged on a real cycle rather than on tests.

**Coordinator's failure first, because it is the reusable part.** I told the
`#282` lane that `#311` and `#312` were "written up and unowned". They were not.
They existed only in a session-local task tracker, which **no other lane can
read**. The lane checked `origin/main`, found nothing, and said so. That is the
same shape as `SYNDICATE_BOARD_L2A_ENABLED` being set on the service that never
runs the code: **a record kept somewhere with no causal path to its reader is
not a record.** If it is not in `todo.md` on `origin/main`, it does not exist.

Measured by the `#282` lane in `scripts/run_refresh_worker.py`:

1. **The cap is never enforced.** `:1879` computes `active_jobs >= max_active_jobs`,
   writes a `throttled` status, and then `return`s **only under `--run-once`**.
   The long-running loop has no `continue`, so it falls straight through to
   `:1890` and spawns anyway.
2. **Even with a `continue`, it could not fire.** `_current_active_job_count`
   (`:1269-1280`) returns **0** when the manifest is `running` with no live pid —
   which is *exactly* the condition `_has_pending_external_contract`
   (`:1365-1372`) requires in order to re-claim. **The two predicates are
   mutually exclusive by construction, so the cap reads zero precisely when the
   thing it bounds is running.**

`SYNDICATE_REFRESH_WORKER_MAX_ACTIVE_JOBS` is unset on both workers → defaults
to 1. A limit of 1 that cannot be reached and would not be honoured if it were.

This is the root defect behind `#279`'s nine OOM kills. `#282` **bounds the
damage and does not remove it**. Possibly also behind `#318`'s five concurrent
publishers — unverified, and worth checking before assuming the publish endpoint
is the right place to fix that.

### #327 — ARCHIVED (recovered). An 817MB memory excursion at `post_mlb_sim_tick`, and the ring buffer that could not see the stage it happens in

> **Recovered from `eed74665` after I destroyed it.** My `#338` commit `c193c498` was
> built on a STALE working copy and reverted this entry out of `todo.md` (428 deletions).
> The archive commit `7ca3adab` then ran against the already-truncated file, so it
> archived the residual rather than this. Nothing was lost from git, but both working
> files had lost it. Body below is verbatim from `eed74665`.

**Status: measured on production 2026-08-10, re-derived independently from the
raw logs rather than inherited. Not fixed. Filed at the `#285` lane's suggestion
after their verification; the instrument half is sharpened here.**

#### The excursion

refresh-worker `87cdd3e1`, pid 38 (started 15:59:12Z). Three consecutive
`post_mlb_sim_tick` samples:

```
16:32:36   pid38 1050.6   container 1923.9   accounted 1106.0
16:33:14   pid38 1867.4   container 2709.9   accounted 1896.4   <-- +816.7 / +786.0 / +790.5
16:33:48   pid38 1079.9   container 1928.4   accounted 1135.1
```

**All three metrics move together, which is the check that matters.** A `/proc`
artifact moves `rss_mb` alone; `container_memory_mb` comes from a different
source entirely (cgroup), so a lockstep +786MB there makes this real memory
rather than a bad read. Back to baseline within 72 seconds.

#### Why it deserves an ID separate from `#285`

`#285` owns a **ratchet** — ~11 MB/min, sustained, with or without the arena
cap. This is a **spike**: 817MB up and back in ~72s. Different shape, different
place (`post_mlb_sim_tick`, not the overview build everyone has been blaming),
and it does not move `#285`'s rate one way or the other.

**Headroom is the reason to care.** 1867MB process / 2710MB container leaves
~1.4GB. A hydrated overview measured at ~+700MB tonight, landing on the same
cycle, puts the container near **3.4GB against a 4GB cap**. Nobody has been
looking here.

#### The instrument gap, and it is worse than "a stage logs to stderr"

The `#285` lane found their RSS series was blind to this: **172 pid-38 samples
in the logs against 39 in the ring buffer at
`/api/ops/intelligence/memory-diagnostics` — they had been reading 23%.** And
the missing 77% is not a random sample; it carries the highest values:

```
post_mlb_sim_tick                n=34  max=1867.4  median=959.6   <- invisible
live_lens_tick_after_build_mlb   n= 9  max=1118.7  median=985.4   <- invisible
post_pool_assembled                    max=1044.1                 <- all they saw
```

**The sharpened mechanism, verified from the code here:** it is NOT that the sim
tick calls a different, humbler logger. **There are TWO functions with the SAME
NAME and only one of them persists:**

| | writes stderr | writes ring buffer |
|---|---|---|
| `pipeline/intelligence_state.py:2649` `_diag_log_all_process_memory` | yes | **yes** (`_diag_dump_checkpoint_to_disk`) |
| `scripts/run_refresh_worker.py:2086` `_diag_log_all_process_memory` | yes | **no** |

`run_refresh_worker.py:2306` calls `_diag_log_all_process_memory("post_mlb_sim_tick")`
— which reads, at the call site, exactly like the one that persists. **A reader
checking "is this stage instrumented?" sees the right function name and stops.**

This is the same shape as `#317`'s two board-snapshot write sites and `#105`
before it: a near-duplicate helper where only one copy receives the fix. The
repo keeps producing them. **Fix by extracting ONE helper, not by adding the
missing line to the second copy** — that is the lesson `#317` had to learn twice.

#### UPDATE 2026-08-10 — IT RECURS, IT IS EXCLUSIVELY `post_mlb_sim_tick`, AND IT IS NOT A CADENCE

Owned by the soccer-concurrency lane after `#282`/`#311` closed. **The
instrument fix `3e1096fb` is committed and NOT DEPLOYED**, so none of this came
from the ring buffer — it is all from the log channel, which was never blind.

**First attempt was worthless and the reason is reusable.** I compared every
sample against a fixed 1500MB threshold and got **1733 of 2967 samples over it
(58%)**. That measures the baseline, not an excursion, and it spanned four boots
whose baselines differ. **A threshold test cannot find a spike in a series whose
floor moves.**

The entry's own evidence was never a threshold — it was a *three-sample shape*
(1050.6 → 1867.4 → 1079.9). So the right test is local and boot-relative: how
far does a sample sit above the mean of its two immediate neighbours, never
measured across a restart. Over 5 hours, 3,914 samples, 5 boot segments:

```
15:32:27Z  post_mlb_sim_tick    933.2 -> 1586.7  (+653.5)  container 2296.9
16:14:53Z  post_mlb_sim_tick    937.4 -> 1430.9  (+493.6)  container 2347.3   +42.4 min
16:33:14Z  post_mlb_sim_tick   1120.5 -> 1896.4  (+775.9)  container 2709.9   +18.3 min
16:44:18Z  post_mlb_sim_tick   1160.6 -> 2030.8  (+870.2)  container 2792.7   +11.1 min
```

**1. It recurs.** `n=4` in 5 hours, not the `n=1` this entry recorded. The
16:33:14Z event is the one already filed here (1896.4 accounted vs the 1867.4
pid-38 RSS quoted above — different fields, same event).

**2. Exclusively `post_mlb_sim_tick`, and that is threshold-robust.** At a
400MB bar, **4 of 4**. Dropping the bar to 250MB gives 8, of which 5 are this
stage and the three others are all `live_lens_tick_*` at 287–380MB — **every
excursion above ~490MB is `post_mlb_sim_tick` and nothing else is close.**
Checking two thresholds matters because `n` is otherwise an artefact of the bar
I happened to pick.

**3. It is NOT a cadence, and this entry's caution was right.** Gaps are 42.4,
18.3 and 11.1 minutes — scattered, not periodic. Do not build a "spikes every N
minutes" claim; that remains unsupported with the sample size larger, not
smaller.

**4. THE APPARENT GROWTH IS NOT A TREND CLAIM.** Both the excursion size
(+653 → +494 → +776 → +870) and the floor it launches from (933 → 937 → 1121 →
1161) look like they are climbing, and container peak went 2297 → 2793. **That
is four points, and this file records the same error at least three times** —
the "accelerating OOM loop" from three boot gaps, the 5-sample live-lens median,
the n=7 memory peak. **I am explicitly not claiming a trend.** It is worth
re-measuring over a longer window; it is not worth acting on. [[a rate, not a count]]

**Headroom, stated as the reason to care:** peak container 2792.7MB against the
4096MB cap — **68%**, from a stage nobody was watching, with the hydrated
overview (~+700MB) able to land on the same cycle.

#### ATTRIBUTION 2026-08-10: `post_mlb_sim_tick` IS A BYSTANDER. FIVE causes eliminated (the fifth retracted, then RESTORED on a direct test), none confirmed

**The stage in the name did not allocate the memory.** At every one of the four
excursions the tick's own `MLB_SIM_TICK` meta reports **every sub-feature
gated**:

```
lookAhead            launched=false  within_check_interval
lookAheadDay2        launched=false  within_check_interval
mlbDailySim          launched=false  intelligence_pipeline_busy
mlbEveningNextDaySim launched=false  before_evening_window
mlbStatcastRefresh   launched=false  within_check_interval
```

**The tick launched nothing and did a handful of gate checks.** It cannot be
holding 817MB. `post_mlb_sim_tick` is simply the stage whose sample lands where
the memory already is — **the label marks the OBSERVER, not the ALLOCATOR**, and
anyone optimising the sim tick on the strength of this stage name will be
working on the wrong code. That is the single most useful thing in this entry.

#### Eliminated, each with its own evidence

**1. NOT a child process.** `accounted_rss_mb` sums every process in the
container, so a sim subprocess would look identical. It is not one — the growth
is inside the long-lived worker:

```
15:32:27  pid 39  +681.1MB of +655.2 total   (104% in-process)
16:14:53  pid 38  +503.5MB of +503.5 total   (100%)
16:33:14  pid 38  +816.7MB of +790.5 total   (103%)
16:44:18  pid 38  +878.5MB of +878.5 total   (100%)
```

**No new processes at any peak.** (>100% because one other process exited in the
same interval.)

**2. NOT the intelligence overview thread.** refresh-worker is one multithreaded
process, so a background thread could hold it and no per-process metric could
tell. Tested rather than assumed: `build_candidate_pool_start` /
`OVERVIEW_SPORT_BEGIN` follow each peak by **+83s, +88s, +75s, +72s** and read
**949.8 / 957.2 / 1121.4 / 1181.3 MB** — baseline. The overview builds *after*
the excursion has already drained.

**3. NOT a large artifact read.** The whole keyvalue store is **37.04MB**, largest
single key **8.39MB**. No parse of that can reach 800MB.

**4. NOT the `#322` book-grid tick** — the most attractive candidate, since it
reads the 207MB MLB `book_quotes` shard uninstrumented between samples.
**Correlation is suggestive and the mechanism does not survive:** every peak
follows a `BOOK_GRID_TICK` by **2.5 / 4.9 / 3.2 / 3.8 min**, but samples are
~30s apart, so a direct allocation would surface at the *next* sample, not five
minutes later. Decisively, there are **13 book-grid ticks against 4 peaks** in
the same window — if it were the cause it would fire three times as often as it
does. **A correlation that requires the effect to arrive 5 minutes late and skip
two thirds of its causes is not a mechanism.**

#### What that leaves, stated as a search space rather than a suspicion

In-process, in the long-lived worker, 493–878MB, released within ~72s, **not
aligned with any instrumented stage**. Every named stage around the peaks reads
baseline. So the allocator is in an **uninstrumented gap** — and one is already
visible: the live-lens loop's last stage sample (`live_lens_tick_after_nfl`)
precedes its own `TICK_COMPLETE` by ~18s, with the publish sweep inside that
window.

**Not claimed:** that the live-lens publish sweep is the cause. It is the
largest unlit gap adjacent to the peaks, which makes it where to point the next
instrument, not an answer. **That instrument was then built and it eliminated
the candidate — see below.**

**The method note.** Every elimination above came from a field already in the
payload — process tables, tick meta, stage timings. None needed new code.
[[read the field you already have]]

#### REGIME BOUNDARY — EVERY MEASUREMENT IN THIS ENTRY PREDATES 2026-08-10 21:56Z

`SYNDICATE_HYDRATED_OVERVIEW_MIN_REBUILD_SEC=900` was set at **21:56Z** and
verified firing at 22:08:27Z across all 8 sports (board still built,
`count=239`, on cached overviews). **The hydrated MLB pass — measured at +2.9GB
in 73s — now runs at roughly half its previous frequency.**

Everything below was measured **before** that: the `n=4` excursion table
(15:32–16:44Z), the 15-cycle publish-sweep table (20:33–21:07Z), the
`container_peak` climb 1155 → 2230MB, and the 21:16:54Z mid-sweep catch. **They
describe a noisier background than the one that exists now and are not directly
comparable with anything sampled after 21:56Z.**

Two consequences, and the second is easy to get backwards:

- **Excursions should be EASIER to isolate now.** A quieter baseline means a
  493–878MB in-process allocation stands out further from it.
- **The `container_peak` series is regime-split.** A "the baseline climbs
  1155 → 2230MB" claim is about the old regime. Re-derive it before reusing it —
  and note the same trap the entry already records: **a fixed threshold over a
  moving baseline measures the population, not the exception**, and the baseline
  just moved for a new reason.

#### 5. RESTORED, on the test the first version was never held to. The publish sweep is NOT the allocator

**Read this before the retraction below, which it supersedes.** The retraction
was right to make — the instrument really was blind — but the inference drawn
from it was weaker than I presented, and the direct test now says so.

**THE DECIDING OBSERVATION, 2026-08-10 22:40:42Z:**

```
excursion  rss 1389.0MB  container 2546.9MB  +529.5MB above neighbours
           NOT inside any publish sweep window
           nearest sweep 22:42:50-22:42:52, 127s away
```

**+529.5MB is squarely in the 493–878MB `#327` class, and no sweep was
running.** An excursion of the same magnitude occurs without the publish path,
so **the sweep is not necessary for it.** That is a direct exclusion, not a
magnitude argument.

#### THE NUMBER THAT SHOULD HAVE TEMPERED MY RETRACTION: a 20% base rate

Measured over 2,012s: **14 completed sweeps, 403s of total sweep time — a 20.0%
duty cycle.** So a randomly-timed excursion lands inside a sweep **one time in
five.**

**The 21:16:54Z coincidence I overturned an elimination on was a 1-in-5 event.**
I reported it as though it implicated the publish path. It did not: it was the
expected outcome a fifth of the time, and I never computed the prior before
acting on it. Coincidence with a process that is running 20% of the time is
close to no evidence at all.

**This is the same defect as the one it replaced, pointed the other way.** The
first elimination came from an instrument that could not see the event; the
retraction came from a coincidence whose base rate I did not check. Both were
confident, both were about the publish path, and both were wrong for reasons
available at the time. [[a rate, not a count]]

#### Three independent grounds now, which is why this one should hold

1. **Necessity fails.** A +529.5MB excursion with no sweep running (above).
2. **In-sweep sampling finds nothing.** Five sweeps of 47–55 artifacts,
   up to 43.3s and 22 polls, **max lift +14.5MB** above their own endpoints —
   on an instrument that reads the same cgroup counter as the excursion and
   therefore *cannot* miss a real spike in its own window.
3. **The one coincidence was expected.** 20% duty cycle, n=1.

**Still not claimed:** what *does* allocate it. This restores an elimination; it
does not identify a cause. Five eliminations, cause unattributed.

**Method note, and it is the reusable part.** The question that resolved this
was not "how big can the sweep get" — sweep size was always a proxy, and my own
`LARGE_SWEEP=60` threshold turned out to be unreachable (sizes plateaued at 47,
having plateaued at 34 earlier; the 73–103 in the loop's comment may describe a
configuration that no longer exists). **The question that resolved it was
whether the excursion needs the sweep at all.** Necessity is cheaper to test
than magnitude and it does not depend on catching the biggest case.

#### 5-superseded. RETRACTED — the publish sweep is BACK, and my instrument's blind spot is why I got it wrong

**READ THIS BEFORE THE ELIMINATION BELOW. I retract it.** The excursion was
caught happening *inside* a publish sweep, and my `before`/`after` pair is
structurally incapable of seeing it.

```
21:16:18  live_lens_publish_before   rss=1081.5   container=2470.5
21:16:54  post_mlb_sim_tick          rss=2051.7   container=3459.1   <-- +970MB, MID-SWEEP
21:17:11  live_lens_publish_after    rss=1233.9   container=2628.9   published=94 elapsed=53.6
```

**A 94-artifact, 53.6-second sweep. Thirty-six seconds in, RSS was +970MB above
the sweep's own `before` sample — and back down before its `after` sample.** The
endpoints report a +152MB delta across an event whose peak was +970MB.
`container` hit **3459.1MB, 84% of the 4096 cap** — the highest reading recorded
tonight.

**A BEFORE/AFTER PAIR CANNOT MEASURE A TRANSIENT ALLOCATED AND RELEASED BETWEEN
ITS ENDPOINTS.** I designed the instrument, argued an elimination from it, and
the elimination was an artifact of the instrument's blind spot. Same class as
every other failure in this file — an instrument answering rather than erring —
except this one is mine, built *after* writing that lesson down twice.
[[instrument blindness]]

**And the sample that produced the elimination was the wrong population.**
Sweeps of 15–34 artifacts have small deltas because they are small sweeps. The
73–103 range the loop's comment cites **does occur** — 94 and 99 artifacts,
observed 21:15–21:17Z — I simply had not caught one in the first 36 minutes and
generalised from the small ones. The caveat I attached ("max observed 34, a
non-linear blow-up is not formally excluded") was pointing exactly at what then
happened, which is an argument for weighting one's own caveats more heavily
than one's conclusion.

**Correction to a number I published:** `b9b77eaf` says the sweep accounted for
**−8%** of the excursion. That came from my watcher pairing `befores[0]` with
`afters[-1]` across a ±120s window spanning **three** cycles. The correct
within-cycle delta is **+152.4MB**, and the mid-sweep peak is **+970MB**. The
−8% figure is void.

#### What is now claimed, and what still is not

**Claimed:** the excursion is coincident with a large publish sweep, and the
publish path is a live candidate again. One observation.

**NOT claimed:** that the sweep causes it. Coincidence with a 53.6s window that
covers a large share of the cycle is weak on its own, and the four other
eliminations are unaffected. **What would settle it:** sampling *inside* the
sweep — per-artifact or on a timer — rather than at its boundaries. That is the
next instrument, and the reason to build it is that the current one has now
demonstrably failed at exactly the case it was built for.

#### The superseded elimination, kept because the data is real and the reasoning is instructive

`489ddbb5` lit the gap (`live_lens_publish_before` → `after`, plus the pull at
cycle start). Live on refresh-worker from **20:32:47Z**. **15 paired cycles**:

```
published  elapsed_s   d_container    d_rss      container_peak
   15          3.4        +43.3        +9.4         1155.5
   23          7.1       +199.7       +78.0         1570.0   <- outlier, see below
   15          8.2        +18.8        +0.0         1670.6
   15          5.1        -13.7       -26.3         1686.5
   15          1.8         -0.5        +0.0         2039.5
   15         35.3        -41.2       -41.7         2049.2
   15         12.9         -0.5        +0.0         2077.9
   15          7.7         +0.3        +0.0         2099.4
   15          2.3         -7.3        -0.3         2357.3
   15          4.7        +15.8       +16.2         2166.8
   15          4.9         +3.4        +3.2         2208.0
   17          5.6         -8.0        -1.0         2202.6
   30         13.8         +2.6        +0.0         2230.3
   32          3.7         -0.4        +0.0         2240.5
   34         47.3        +12.9       +12.9         2209.9
```

**Two independent reasons this is not the 493–878MB allocator:**

1. **Wrong magnitude by one to two orders.** Excluding the outlier, every cycle
   sits within ±44MB and most within ±20MB. **Many are NEGATIVE**, which is what
   a sweep whose allocations are freed before the after-sample looks like
   against a drifting baseline.
2. **No scaling with sweep size, which is the load-bearing test.** The *largest*
   sweep (34 artifacts) cost **+12.9MB**; a 15-artifact sweep cost **+43.3MB**.
   Marginal cost across the observed range is **−1.60 MB per artifact** —
   negative, i.e. no relationship at all. A linear model predicting ~500MB at
   103 artifacts is not merely unsupported, it is contradicted in sign.

**The `elapsed_seconds` check closes the obvious objection.** The loop's own
comment cites sweeps of "48–74s per cycle at 73–103 artifacts", so the natural
rebuttal is that only small fast sweeps were observed. **A 47.3-second sweep was
observed and cost +12.9MB** — squarely inside the cited duration band. Duration
does not buy memory here either.

#### The caveat that keeps this at "eliminated", not "excluded"

**Max observed sweep is 34 artifacts against the 73–103 the comment cites.** The
flat-to-negative slope from 15→34 makes a *linear* blow-up at 103 untenable, but
a **non-linear** one is not formally excluded. Steady state is ~15/cycle rising
to ~34 as the worker warms, so a 73–103 sweep likely needs a batch write and may
be rare. A watcher is running for one.

**And one point is unexplained: 23 artifacts → +199.7MB**, larger than every
bigger sweep in the table. Whatever produced it, **it was not sweep size** —
which makes it interesting rather than dismissible: it may be the same
uninstrumented something the excursions are, caught in passing.

#### A thing visible only because the deltas are near zero

`container_peak` climbs **1155 → 2230MB across 25 minutes** while the publish
deltas hover around nothing. That is `#285`'s ratchet accumulating underneath,
entirely independent of this path — and a standing reminder that **the baseline
moves on its own while you are measuring deltas against it.** A fixed threshold
over this series would have flagged the tail and called it an excursion.

#### A correction to my own instrumentation claim

I wrote that the sample "carries `published_count`/`failed_count`/
`elapsed_seconds`, so one line beats correlating two log streams". **True of
stderr, FALSE of the web-visible record.** `update_process_memory_high_water`
persists a fixed subset — `stage`, `peak_mb`, `container_memory_mb`,
`accounted_rss_mb`, `pct_of_max`, `observed_at`, `pid`, `processes` — and drops
arbitrary `**extra`. So `high_water` shows `published_count=None`.

**I nearly reported that `None` as evidence the sweep had crashed**, since my
own code sets those fields to `None` only on the exception path. It is the
schema, not a crash. Checking the emitter before interpreting the absence is the
only reason a false finding did not go out. [[absent signal is about the emitter]]

Small gap worth closing when something else deploys: **a peak without its
artifact count is a number without its denominator**, and the peak is exactly
where that denominator is wanted.

#### What is NOT claimed

- **Not accumulation.** It returns in 72s. `#285`'s ratchet is unaffected.
- ~~**Not recurring.** This is **n=1 in a 39-minute window**.~~ **SUPERSEDED —
  it DOES recur: `n=4` in 5 hours (see the 2026-08-10 update above).** The
  original was correct for the window it had; a 39-minute window simply could
  not see a ~75-minute inter-arrival gap. **The half of this bullet that
  SURVIVED is the important one: it is still NOT a cadence** — gaps of 42.4,
  18.3 and 11.1 minutes are scattered, and "spikes every N minutes" remains
  unsupported with the sample four times larger.
- **Not attributed to a cause.** Nothing here says what allocates the 817MB.
- **Not `_keyvalue_backed` (`#324`).** That change only re-routes which transport
  a write takes, the spike is inside the sim tick, and the trim/gc figures on
  this boot match the previous one.

#### Where it came from, because the path matters

I found the 1867.4 reading incidentally while sampling process lists for an
unrelated zombie question (`#324`), and handed it over rather than sitting on it
because it fell outside the range the `#285` lane was reasoning about. They
verified it, and it exposed a blind spot in their own instrument that they could
not have found from inside it. **Both halves needed the handoff** — the number
was useless to me and the instrument gap was invisible to them.
