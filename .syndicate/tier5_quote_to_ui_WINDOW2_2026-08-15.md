# TIER 5 / D2 — SECOND WINDOW. The latency is bimodal, and a run-lock is the switch.

Measured against production 2026-08-15 11:38–12:00 CDT (16:38–17:00Z), 22
samples at 60 s plus a parallel tick sampler. Read-only. Nothing deployed.
Companion to `tier5_quote_to_ui_2026-08-14.md` (window 1).

**Why a second window:** window 1 closed with two stated gaps — Layer 2 was
confounded by three refresh-worker deploys inside 31 minutes and never rebuilt,
and no deploy-free window had ever been sampled. This window has neither
problem, and it caught a state transition that makes both windows readable.

Deployed commits, re-read in the same step: web `c774fe1a`, refresh-worker
`984e48c8`, live-odds-worker `ccd10349`.

**The window is clean.** Last deploy before it: refresh-worker 03:44:13Z
(**12.9 h earlier**), web 03:29:56Z (13.1 h), live-odds-worker 2026-08-14T19:24Z
(21.2 h). Window 1's confound is absent by construction.

---

## THE HEADLINE — end-to-end is not a number, it is two numbers and a switch

The window caught the system in **both** states and caught the transition
between them.

```
 #  wall(Z)   L1 build   quote age    end-to-end | L2 written  age
 0  16:38:33  16:35:54    19,686.6 s   19,846 s  | 16:38:18     16
 5  16:43:38  16:35:54    19,686.6 s   20,150 s  | 16:38:18    321
 8  16:46:40  16:46:27    20,317.3 s   20,330 s  | 16:44:24    137
 9  16:47:41  --- HTTP 502 x3, web unavailable ---
12  16:50:43  16:46:27    20,317.3 s   20,574 s  | 16:49:42     63
17  16:55:50  16:46:27    20,317.3 s   20,880 s  | 16:54:28     83
18  16:56:51  16:56:49        29.0 s       32 s  | 16:54:28    145   <-- SWITCH
21  16:59:55  16:59:10       169.5 s      214 s  | 16:54:28    328
```

| regime | end-to-end | what governs it |
|---|---|---|
| **starved** | 19,846 → 20,880 s (5.51 → **5.80 h**) | rises exactly 1 s per second |
| **healthy** | **32 s** → 214 s | board rebuild interval |

**In the starved regime the end-to-end figure is not a latency at all. It is a
clock.** It advances one second per second because nothing upstream is moving.
A dashboard reporting "current staleness" would have shown a smooth, confident,
steadily-rising number for six hours.

And the healthy figure — **32 s** — is *better* than window 1's best (143 s).
So the system is not slow. It is either fast or stopped.

---

## The switch is a run-lock, and the causation is measured, not inferred

The parallel tick sampler over the same 22 minutes:

```
16:39 -> 16:55   17 consecutive ticks   ok=False skipped=True   pid=4047 holds the lock
16:56:26         ONE tick               ok=True                 lock released
16:56:49         next L1 build carries a 29 s quote  ->  e2e 20,880 s -> 32 s
16:57 -> 17:00   ticks refused again                            pid=5681 holds the lock
```

**One tick in eighteen got through, and that single tick collapsed end-to-end
latency from 5.8 hours to 32 seconds.**

**CORRECTED 2026-08-15, after tracing the emitters.** The first version of this
file named `JOB_CAP_THROTTLED active=1 max=1` as the mechanism. **That conflated
two different locks**, and the distinction changes the fix:

| | what it is | where |
|---|---|---|
| the lock that refused every tick | per-lane refresh-run lock — raised when the lane manifest is non-terminal and its pid is still alive | `shared/ops_refresh.py:669`, from `_assert_no_active_refresh_run` |
| `JOB_CAP_THROTTLED` | a separate throttle in refresh-worker's job loop, `SYNDICATE_REFRESH_WORKER_MAX_ACTIVE_JOBS` (unset → default 1) | `scripts/run_refresh_worker.py:3496` |

**Raising the job cap would NOT have fixed the capture starvation.** The two
co-occur because both are downstream of one long-running job, which is what made
them easy to confuse — and confusing them points at the wrong remedy, on a
worker that is already memory-constrained.

Tracing the lock holders back through the day on live-odds-worker:

```
pid 2313  11:39 -> 12:05      pid 81    14:36 -> 15:02
pid 3614  12:07 -> 12:33      pid 1077  15:04 -> 15:29
pid 4678  12:35 -> 13:01      pid 2071  15:32 -> 15:57
pid 5769  13:04 -> 13:20      pid 3067  16:00 -> 16:19
pid 7114  14:08 -> 14:34      pid 4047  16:27 -> 16:56
                              pid 5681  16:57 -> ...
```

**Each run holds ~25 min and releases for ~2 min before the next takes it —
roughly 92% occupancy for six hours.** The 60 s tick interval is irrelevant;
what paces the system is how long one job holds the single slot, and whether a
tick happens to land in a 2-minute gap.

Corroborated independently from the artifact rather than the logs — every
distinct `captured_at` minute in `mlb_source/tracking/book_quotes/2026-08-15.jsonl`
(22,828 rows, streamed from web):

```
04:48  3,622 rows      07:03  1,771   gap  61.0 min
06:02  4,663  gap 74.0 09:06  5,918   gap 123.0
                       10:07  2,681   gap  61.0
                       11:07  2,661   gap  60.0   then 5.8 h of nothing
```

The pregame beat today is **~60 min, not 121.6** (one 123 = a skipped slot).

---

## METHOD — I made window 1's exact error and the data caught it

My first draft of this file, written at sample 6, said capture had **stopped**.
It had not; it resumed at 16:56 while the poller was still running. That is
precisely the failure `state.md` already records from window 1 — *"'Capture
stopped at 15:10:44' came from ONE read of a bursty quantity taken inside a
gap"* — and I reproduced it despite having read that warning the same session.

**The rule that actually works, restated: never characterise a bursty pipeline
from samples taken inside one of its gaps. Sample across at least one
transition, or report a bound rather than a state.** The 22-sample window is
what made the bimodality visible; any 6-sample window would have produced a
confident and wrong answer, in either direction.

---

## The cooldown is NOT today's constraint — a correction to the program plan

Over 11:00–16:45Z on **live-odds-worker** (the service that emits the line):
`PREGAME_RELAUNCH_COOLDOWN_SKIPPED` fired **once**. Not once per tick — once in
5.75 hours.

I first counted this on refresh-worker and got 0, which would have been a
satisfying confirmation and was **meaningless**: that service does not emit the
line. Liveness control on the correct service — live-odds-worker emitted 5 lines
since 16:00Z — so the near-absence is real and not a dead collector.

**Consequence:** Tier 0's `0.1` (per-sport cooldown) remains correct for the
empty-slate pregame regime window 1 measured, but it would **not** have
prevented today's 5.8-hour starvation, and it is not the prerequisite Tier 5
treats it as. Deploying it and re-reading the cadence today would have shown no
improvement and been easy to misread as the fix failing.

**The plan's premise that movement work is "computing on a signal sampled
roughly every two hours" is wrong in both directions.** The signal is sampled at
32 s or not at all. Window 1's finding that the operative defect is
`_ODDS_HISTORY_LIMIT = 20` stands and is strengthened: during a lock chain the
20-point buffer's newest sample is hours old, so `movement_velocity` and the
steam detector report a velocity of zero that is indistinguishable from a
genuinely quiet market. **Nothing in that family should be extended until it
carries the age of its newest sample.**

---

## Layer 2 is healthy in this window — window 1's verdict does not generalise

`written_at` advanced four times: 16:38:18, 16:44:24, 16:49:42, 16:54:28 —
**rebuild gaps of 6.1 / 5.3 / 4.8 min**, artifact age 1–328 s. Against window
1's ≥60 min frozen artifact, and the ledger's 19.6 min (post-`#387`) and 104.7
min (pre-`#387`) baselines, **this is the healthiest Layer 2 yet measured.**

Window 1 concluded "Layer 1 clean, Layer 2 broken." Twelve hours later it is
exactly inverted: Layer 2 rebuilds every ~5 min while the quotes feeding it are
5.8 h old. **Neither window's verdict is the system's verdict** — which is the
main reason a single window should not have been trusted.

---

## Incidental, recorded not diagnosed

- **3 consecutive HTTP 502s from web, 16:47:41–16:49:42**, both endpoints,
  self-resolving. Web's last deploy was 13 h earlier, so this is not a deploy.
- **`anyLive: true` with zero live rows on the board.** The tick reports
  `phase: "live"` and gates MLB/WNBA off via `pregameCadenceSkipped`, while the
  served shortlist carries 150 rows (90 MLB / 42 NFL / 18 WNBA) and **zero live
  in any sport**. Flagged, not resolved: it needs the board-build loop, which
  this session was told not to touch, and it overlaps `#435`.

---

## What this window does NOT establish

- **Nothing about the NFL live-edge fix (`1d15686b`).** `live_edged` and
  `nfl_live_edged` were 0 in all 22 samples, but there were **zero live rows of
  any sport** the whole window, so the instrument could not read unhealthy. A 0
  here is not evidence the guard works; it is evidence there was nothing to
  guard. The fix remains **committed, undeployed, unverified in production**,
  with window 1's 5 live NFL edges at 02:37Z still the baseline to beat.
- **One sport, one day.** The ~60 min pregame beat, the ~25 min lock period and
  the 92% occupancy each rest on a single afternoon.
- **The healthy regime is 4 samples.** 32 / 93 / 154 / 214 s spans two builds.
  It is enough to falsify "the system is slow"; it is not a distribution.

---

## For the product decision (already taken: build the live game-line projection)

Window 1 said latency is not the obstacle. **That survives — and this window
makes it stronger and more conditional at once.** 32 s end-to-end is an
excellent budget for a live game-line product; the steady-state pipeline is
demonstrably capable.

The obstacle is not speed. It is that **the feed can stop for six hours while
every downstream surface keeps serving confidently**, and that the thing which
stopped it is a single job slot held by unrelated work.

Two concrete prerequisites, both upstream of any projection work:

1. **An alarm on quote-feed age.** Not on cadence — on the age of the newest
   sample. Today's outage was invisible to every existing signal.
2. **The job-cap contention** (`active=1 max=1`). A live product cannot depend
   on winning a 2-minute gap in a 25-minute lock cycle.

A live game-line projection shipped onto this substrate this afternoon would
have published live edges against 5.8-hour-old prices — strictly worse than
publishing nothing, and the same class of defect as the NFL live edges one layer
further upstream.

---

# PREREQUISITE WORK — what was built, and what was deliberately not

The two prerequisites this file named. One is built; the other is diagnosed and
handed over, because the obvious fix for it is actively dangerous right now.

## 1. BUILT — an alarm on quote-feed age

`syndicate/features/shared/quote_feed_age.py` + `GET /api/ops/quote-feed-age`.

Reports the **age of the newest quote sample per sport**, independent of any
board build, because that is the only quantity that moved during today's outage.
An O(1) tail read of the shard, so it costs the same on a 217 MB shard as on a
10 MB one and is safe to call from web.

**Validated against the real production shard, not a fixture:** the tail read
recovered `2026-08-15T11:07:48.411313+00:00` from the 10.4 MB streamed shard and
a full scan of the same file agreed exactly.

**Two design decisions worth arguing with:**

- **Unknown is not OK.** A missing or unreadable shard reports `unknown`, never
  `ok`. The failure being guarded is "the feed stopped and everything looked
  fine"; a permissive default reproduces that bug one layer down. Four tests pin
  this and are mutation-pinned — flipping the initial status to `ok` turns
  exactly those four red and leaves the ten threshold/tail tests green.
- **One threshold, 3 h, env-tunable** (`SYNDICATE_QUOTE_FEED_STALE_SECONDS`).
  **The honest cost: detection lag is 3.0 h.** It fires at 14:07:48Z on today's
  outage and stays lit for 2.8 h of the 5.8 h. It cannot be tightened without
  false-alarming, because the widest *healthy* pregame gap measured is 123 min.
  During a live slate the feed runs at ~60 s, so a 3 h alarm is ~180× slower
  than it could be. **The real answer is per-regime thresholds**, which needs a
  trustworthy regime signal — and today the tick's own `anyLive` was `true`
  while the board carried zero live rows in any sport, so that signal does not
  exist yet. This is the version that does not depend on one.

I opened the lane claiming it would have fired at 14:00Z. **That was wrong** —
age at 14:00Z is 10,332 s, under the threshold, so it reports `ok`. The lane and
the tests now pin the corrected 14:07:48Z, and the test that asserts the
comfortable answer was deliberately written to assert the uncomfortable one.

## 2. NOT BUILT — the run-lock contention, and why touching it now is wrong

The obvious reading of "job-cap contention" is *raise the cap*. **Three separate
reasons that is the wrong action, in order of severity:**

1. **It would not have worked.** The lock that starved capture is the per-lane
   refresh-run lock (`ops_refresh.py:669`), not `JOB_CAP_THROTTLED`. Different
   mechanism, different file. See the correction above — I published the wrong
   one first.
2. **It would make the live incident worse.** `SYNDICATE_REFRESH_WORKER_MAX_ACTIVE_JOBS`
   is unset, so the default of 1 applies. Raising it doubles concurrent memory
   on a 4 GiB worker that is *currently the subject of an active OOM
   investigation* (`#435`). Measured on that worker during this window:
   `container_memory_mb` 3,227 of 4,096, headroom 868 MB. There is no room for a
   second concurrent job.
3. **The files are claimed.** `live_refresh_loop.py` is held by the OPEN
   `live-game-line-projection` lane; `ops_refresh.py` and the worker loop sit
   inside `#435`'s territory.

**The actual shape of the defect, for whoever owns it.** The lock is *per lane*,
not per sport — so one long refresh run silences odds capture for **all eight
sports**, exactly the way the pregame cooldown did before `ea8fad58` made it
per-sport. That is the same bug in a second place, and `ea8fad58` is the
worked example of the fix, including its rollback-safety pattern (write the
old shape, let an absent entry inherit the legacy value).

**Three options, cheapest first, none taken here:**

- **Scope the lock by sport**, mirroring `ea8fad58`. Removes the coupling
  without changing concurrency or memory. Most likely correct.
- **Shorten the lock-holder.** Each run holds ~25 min; the 2-minute release
  windows are what capture is currently surviving on. Why one refresh run takes
  25 minutes is not established here.
- **Raise the job cap.** Only after `#435` closes, and only with a memory
  measurement — not before.

**Recommended sequencing:** deploy the quote-feed alarm *first*, so the run-lock
work has an instrument that can tell whether it worked. Right now any fix to the
lock would be evaluated against the same green dashboard that hid the outage.
