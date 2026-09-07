# Handoff: `/api/intelligence/query` — 8 concurrent misses do 8 rebuilds

**For whoever holds `pipeline/intelligence_state.py`.** From lane
`web-oom-profiler-steady` / session `b2b5b45b`, `#632`.

**The substance is already on `main` and tested** (`df6ec73b`:
`syndicate/features/shared/single_flight.py` + `tests/test_single_flight.py`, 15
threaded tests). All that is left is a **48-line diff to `intelligence_state.py`**,
reproduced verbatim in
`.syndicate/handoff_2026-09-07_intelligence_query_singleflight.patch`. I did not
leave your file edited — I applied the patch locally to measure it, then reverted.

---

## Who I could not hand this to

`check_lane_claims.py` says **three OPEN lanes** name this path in their `Files:`
block: `polymarket-yes-leg-binding` and `layer2-cap-raise` (both session
`5611932c`), and `layer2-sim-disagrees` (session `3492626c`). **Neither session
appears in `list_sessions(include_archived=True, limit=80)`**, which reaches back
to 2026-08-31. `3492626c` was already established as unreachable by three separate
lanes, which took paths from it on explicit user decisions.

So this is a handoff with no addressee. It is written down rather than acted on,
and the decision to land it is the user's.

## The measurement

`/api/intelligence/query` runs a **5-second median and an 18-second max** in
production. It is one of the routes starving web's thread pool: **32.5% of
requests exceed the 5-second health-check budget**, and that is what actually
restarts the instance — **35 `server_failed` events with zero `evicted=True`**.
Web is not being OOM-killed; it is timing out.

## The cause — two things compounding

**1. The read and the write have nothing between them.**
`_COMBINED_INTELLIGENCE_RESPONSE_CACHE` is read at `intelligence_state.py:8599`
and written at `:8861`. No lock, no in-flight marker. So N concurrent misses each
start their own 5–18 s rebuild. Web has **8 request slots**
(`WEB_CONCURRENCY=2` × `GUNICORN_THREADS=4`), so one expiry can put every slot
into the same work at once — and `/healthz` then has nowhere to run.

**2. The TTL is shorter than the rebuild.**
`SYNDICATE_INTELLIGENCE_COMBINED_BOARD_CACHE_SECONDS` defaults to **15 s**
(`:8493`) while the rebuild costs 5–18 s. Past ~15 s the entry is stale the moment
it is written, so every request rebuilds. That is a collapse mode, not a slow path.

## The A/B, measured both ways

Driving the **real** `read_combined_intelligence_response` with 8 threads and a
stubbed `_read_single_date_response_for_combining` that sleeps 1 s:

| | date-reads | elapsed |
|---|---|---|
| unpatched (`main` today) | **8** | 1.00 s |
| patched | **1** | 1.01 s |

**Read that carefully: elapsed is the SAME, and I am not claiming a latency win
from this harness.** The stub sleeps, so the threads do not contend and 8 parallel
sleeps take as long as 1. What collapses is the **work count, 8× → 1×**. In
production each of those rebuilds occupies a gunicorn slot for 5–18 s, so eight
concurrent rebuilds is the whole pool — that is the failure, and that is what
this removes. The wall-clock claim would need a load test against production,
which I have not run.

## Why `SingleFlight` and not `SingleFlightCache`

The module ships both. **The call site needs the one that stores nothing.**

`_COMBINED_INTELLIGENCE_RESPONSE_CACHE` is bounded by **row count**, not entry
count, and the comment at `:8435` says why: `#632` measured it at **37.50 MB while
obeying its 32-entry cap**, because entry size varies by orders of magnitude with
slate size. Dropping in a generic entry-capped cache would reintroduce exactly the
bug that bound was added to fix. So the patch leaves the store and
`_prune_combined_intelligence_response_cache()` completely untouched and adds
coordination beside them.

## Why the marker is a lease and not a lock

A builder that dies without releasing would wedge the key forever under a plain
lock. With a 90 s lease it delays the key instead. That is what makes the diff
small enough to review: **no `try/finally` wrapped around a 250-line function
body.** I checked the function has exactly two exits — `:8601` (the cached fast
path, before any marker is taken) and `:8863` — so one `finish()` before the final
return covers every normal path and the lease covers the exception path.

## What I verified, and what I did not

**Verified:** 15 threaded tests — exactly one rebuild among 8 callers, a cold key
waiting rather than duplicating, staleness bounded, the builder running outside
the lock, a failing builder not wedging the key, an expired lease being adoptable,
and keys independent. With the patch applied: the module imports, the app builds,
and the 8-thread A/B above runs against the real function. `git apply --check`
passes against the reverted file.

**NOT verified:** production behaviour. No load test, and no deploy. The
`COMBINED_BOARD_SERVED_STALE` log line the patch adds is what would prove it
firing in production — grep for it after a deploy, with a request-count
denominator beside it.

**One judgement call worth your eye:** `finish()` is called unconditionally rather
than guarded by an ownership flag. In the rare fall-through case (the in-flight
rebuild timed out and we build anyway) we may release a marker we do not own. That
can cost a duplicate build; it cannot produce a wrong answer, because the release
happens *after* the cache write, so any woken waiter finds fresh data. Carrying an
ownership flag 260 lines down struck me as the more fragile of the two. Disagree
and it is a two-line change.

## Related, from the same measurement

`/api/board/game-chips` is bimodal — 11 ms typical, 11.6 s worst, the signature of
a cache miss doing real work in the request path. And `request_path_guard` is
already logging a live upstream ESPN fetch inside a Flask handler by name:
`compute in request path (operation=wnba_has_games_for_date_espn_fetch)`.
Both are unclaimed by me.
