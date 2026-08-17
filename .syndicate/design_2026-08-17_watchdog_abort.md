# Design — giving the memory watchdog the ability to ACT

> Status: **DESIGN ONLY. Nothing built, nothing deployed.**
> Lane: `refresh-worker-oom-recurrence`. Author session: `refresh-worker-oom-trace`.
> Written 2026-08-17 ~00:5xZ, on the evidence gathered 23:00Z–00:45Z.

## 1. What is proven, and what is not

Proven tonight, by measurement, and recorded in `deploys.md`:

- The allocator is **downstream of `apply_game_board_contract`**, inside a single
  sport's `_build_sport_overview`. Two kills, two different commits:
  `00:19:48Z` on `94447830` (anon 1209→3998MB, ~25s) and `00:32:32Z` on
  `7c2b1a17` (anon 1354→3751MB, ~16s). Both read
  `last_stage=board_contract_end`.
- The board-contract builder is **cheap**: a full `nfl games=16` triplet ran
  mid-climb for **+2MB**.
- `OVERVIEW_STOPPED_FOR_MEMORY` is silent because it is **passing a check it
  should pass**: measured headroom at a real check point was **3341.6MB**, which
  clears both the 1500MB and 3000MB floors.
- Therefore **raising the floors would not have prevented either kill.**

NOT proven, and this design must not assume it:

- **Which** of `_build_sport_overview` / `_emit` allocates.
- **Which sport** is expensive. The `+1.7MB for five sports` figure that sized
  the relaxed floor was taken with MLB-only instruments; seven sports have never
  been separately measurable.
- Whether the retention mechanism at `home.py:6766-6782` (10s TTL against a ~90s
  loop, previous hydrated row retained while the new one builds) is the cause.
  It is a hypothesis with the right magnitude, nothing more.

## 2. The gap, in one sentence

**An observer exists; an actor does not.** `MEMORY_WATCHDOG` already samples on a
clock, saw every excursion at 2s resolution climbing 100–260 MB/s, and can only
print. Every guard that can *act* sits on a stage boundary, and the allocation
does not cross one. `memory_observability.py:758-761` predicted this exactly:
"multi-GB allocations INSIDE one stage … Adding more boundary markers cannot fix
that; only sampling on a clock can."

## 3. Goal

Let the clock-sampling thread stop a hydration pass that is going to die, and
degrade the board instead of losing the process. **Success is not "no
excursions". Success is "the excursion ends in a skipped sport rather than a
SIGKILL that also takes the sims, the odds capture and every other loop in the
process."**

## 4. Mechanism

Three parts. Deliberately no thread-killing, no `PyThreadState_SetAsyncExc`, no
signals — an async exception injected into arbitrary C-level state is a way to
corrupt artifacts mid-write, and this process writes artifacts constantly.

**(a) The watchdog raises a flag.** In its existing sample loop, after computing
the snapshot it already computes:

    if effective_headroom_bytes < ABORT_FLOOR_BYTES:
        _ABORT_STATE["set_at"] = time.monotonic()
        _ABORT_STATE["reason"] = {...snapshot..., "last_stage": ..., "climb": ...}

No new sampling, no new cgroup reads — it is a comparison on a number the thread
already has. This is the only reason the cost argument in §7 holds.

**(b) The hydration loop polls it.** In `_build_sport_overview`'s caller
(`intelligence.py:2793-2835`) *and* at existing stage-marker call sites, check
the flag and raise a dedicated `OverviewAbort` exception.

**(c) The loop catches it and degrades explicitly**, emitting the sport it
stopped on, the sports completed, and the snapshot that triggered it.

## 5. Where the checkpoint goes — and the open question that decides it

The obvious cheap answer is: **put the poll inside `log_container_memory`**, so
every existing instrumented point becomes a checkpoint at zero new call sites.

**This depends on a fact I have NOT measured: how many stage markers fire during
an excursion.** The evidence is mixed and I will not paper over it:

- Excursion 1 (`00:19:48Z`): a complete `board_contract` triplet fired mid-climb
  at `00:19:40` (sport=nfl). So markers **do** fire during at least some
  excursions.
- Excursion 2 (`00:32:32Z`): `last_stage` read `board_contract_end` for all
  ~16s. That is consistent with "no new markers" **and** with
  "`board_contract_end` re-firing repeatedly" — `last_stage` cannot distinguish
  them.

**Required measurement before building (M1):** count stage-marker emissions per
second during an excursion, not `last_stage` values. If markers fire several
times per second, (a)+(b) at existing call sites is sufficient and cheap. If an
excursion can run 16s with zero markers, the poll must go somewhere inside the
hydration call tree, which is a much larger and more invasive change.

**Do not build until M1 is answered.** Choosing the cheap option on excursion 1's
evidence alone would ship a guard that is silent in exactly the excursions that
have no markers — the `learnings.md` failure shape "a guard that encodes an
assumption about HOW something fails is silent in the real failure mode".

## 6. What abort must NOT do

- **It must never fire on the `skip_game_hydration=True` path.**
  `intelligence.py:2790` is explicit: that path feeds
  `_source_state_fingerprint`, and truncating its sport list "would key the
  caller's cache off a partial sport list and quietly serve the wrong snapshot,
  which is a worse failure than the one being prevented." The existing guard is
  already conditioned on `not skip_game_hydration`; the abort inherits that
  condition, non-negotiably.
- **It must never write a partial overview into `_HOME_OVERVIEW_CACHE`** or let a
  truncated list reach a fingerprint. An aborted pass yields a result that is
  *labelled* incomplete, or no result at all.
- **It must be inert where headroom cannot be measured.** Local dev has no
  cgroups; `memory_headroom_snapshot` returns `None` there. Unknown must map to
  "do not abort" — the opposite polarity to
  `feedback_unknown_must_not_default_permissive`, and correct here, because the
  cost of a false abort is a silently truncated board on every non-Render
  machine. The asymmetry is deliberate and must be stated in the code.
- **It must not be the reason a worker dies.** Every path wrapped, same standard
  as the watchdog itself.

## 7. Cost, against `learnings.md` "worker periodic work is never free"

`#241` put the worker in a restart loop by adding periodic work, so this needs an
explicit answer rather than a reassurance:

- The watchdog side adds **one integer comparison per existing sample**. No new
  thread, no new timer, no new cgroup read.
- The hydration side adds **one dict lookup per existing stage marker**. No new
  markers.
- Nothing is added to the request path; web does not run these loops at all
  (`state.md`: the intelligence background loop is `true` on refresh-worker only),
  so this is inert on the 2GB service.

If M1 forces the poll into the hydration call tree, **this cost argument no
longer holds and must be redone.**

## 8. Threshold

Trigger on **effective headroom below a hard floor**, using the same
`max_bytes - unreclaimable_bytes` quantity the existing guard uses — the one
`#417` established after proving that page-cache LRU shuffling made the old
quantity move the wrong way.

**Do not gate on climb rate.** `climb_mb_per_s` is excellent for a human reading
a log and is a bad thing to make a decision on: it encodes an assumption that the
excursion is fast, and the first excursion that arrives slowly would walk straight
past it. Log the rate in the abort reason; do not condition on it.

Floor value is **deliberately left unset in this document.** It should be chosen
from M2 below, not from intuition, and not from the existing 1500/3000 constants —
those were sized for a different question (can the NEXT sport start) and this one
is different (must the CURRENT sport stop). My memory of this codebase says stale
constants outlive the reasoning that produced them; picking a number here without
M2 would be the same mistake one layer down.

**Required measurement (M2):** the distribution of effective headroom at the
moment each excursion begins, across ≥5 excursions. The floor must sit above the
worst observed *starting* headroom that still died, and below the routine
operating headroom (~3300MB measured tonight), or it will either never fire or
fire constantly.

## 9. Verification — how we prove it works, and how we prove it can fail

Per `learnings.md` "shipping a verification you have not falsified":

1. **It fires.** Force an excursion (or lower the floor to just under current
   headroom on a scratch deploy) and require an `OVERVIEW_ABORTED` line naming
   the sport, sports_done, and the snapshot.
2. **It does not fire in normal operation.** A window with no excursion must
   produce zero aborts. A guard that fires constantly is a board outage.
3. **The skip-hydration path is untouched.** Assert no abort can be raised when
   `skip_game_hydration=True`, by test, not by inspection.
4. **The fingerprint is unaffected.** Compare `_source_state_fingerprint` across
   an aborted cycle and a clean one; it must be identical.
5. **Inert without cgroups.** The full suite must pass on a dev machine with no
   cgroups and produce zero aborts.
6. **The real test — a kill that becomes a skip.** The success criterion is a
   window in which an excursion occurs, an abort is logged, and there is **no
   `oomKilled` event**. Anything less is a code change with no evidence.

## 10. Rollout

One change, staggered and measured, per the session protocol. `/preflight`
first. Parent the deploy branch on the **live SHA**, not `main` — refresh-worker
runs off-main (`fdc72dd0` was on `deploy/wnba-live-tier`), and this session
already recorded what deploying `main` would have carried.

## 11. The honest summary

This design is a **containment measure, not a fix.** It converts a process kill
into a degraded board. The actual defect — a single sport's hydration allocating
+2.4 to +2.8GB — is untouched and still unattributed, and §1 lists exactly how
much of it remains unknown. If the retention hypothesis at `home.py:6766-6782`
is right, the real fix is upstream of everything described here, and this abort
should be regarded as the thing that keeps the worker alive until that is found.
