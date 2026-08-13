# Drain-and-restart for refresh-worker

**Status:** proposal, unowned, nothing implemented.
**Written 2026-08-13 00:2x UTC**, from the 2026-08-12 session in which four
lanes deployed refresh-worker 25 times in 17.8 hours and destroyed roughly half
that day's MLB sims plus at least one 23-minute board build.

This is not a bug report. Every individual deploy that night was announced,
gated, and made in good faith. The conclusion is that **refresh-worker is
effectively undeployable during a live slate**, and no amount of care at the
deploy site fixes that.

---

## 1. The problem, measured

`refresh-worker` runs two kinds of long, non-resumable work:

| work | observed duration | resumable? |
|---|---|---|
| board build (`collect_candidates`) | 804s / 1080s / 1372s, and **77 min once** (see `intelligence.py:9951`) | no |
| MLB sim (`fingerprint_change` resim) | no ETA; 15+ min observed | no |

A deploy kills both. Render attaches a 50 GB disk to this service, which forces
single-instance and therefore **stop-then-start** — there is no rolling deploy
available to us, so every deploy is a hard kill of whatever is running.

**During a live slate these two overlap almost continuously.** The `#403` gate,
which blocks while a board build is in flight, ran for 45 minutes on the night of
2026-08-12 and **never found a clear window**: build → sim → second build. That
is not bad luck, it is the steady state. A guard that correctly refuses every
window is telling you the deploy model does not fit the workload.

### What the current mitigations actually achieve

- **Announce-and-batch** (the agreed protocol): followed correctly on 2026-08-12
  and still destroyed 23 minutes of board work, because the pre-deploy check
  watched for sims and the thing at risk was a build. Fixed in `#403`.
- **`#403`'s build gate**: correct, and it converts *silent damage* into
  *cannot deploy*. That is a strict improvement and not a solution.

### Two facts that shape the design

1. **`refresh-worker` has no SIGTERM handler at all.** `run_live_odds_refresh_worker.py:350`
   installs one (`_handle_stop` → `_LIVE_REFRESH_LOOP_STOP`); `run_refresh_worker.py`
   installs none. On deploy the process is signalled and simply dies — no
   graceful stop, no record of what was in flight, nothing for the next boot to
   read.
2. **The board build has no resume boundary.** It is one
   `_collect_span("collect_candidates", collect_candidates, ...)` call
   (`intelligence.py:10026`). The `checkpoint` symbols in
   `pipeline/intelligence_state.py` are memory *diagnostics*
   (`dump_process_memory_checkpoint`), not build state. A restart restarts from
   zero.

---

## 2. Why the obvious answers don't apply

**Rolling deploy** — unavailable. The attached disk forces one instance.

**Classic drain** (finish in-flight work during shutdown) — impossible. Render
sends SIGTERM then SIGKILL after a short grace period; a 22-minute build cannot
finish inside it. *(The exact grace period is an open question — see §6.)*

**Just deploy less** — this was the protocol, it was followed, and it still cost
23 minutes. And it does not scale to four concurrent lanes: the cost of a deploy
is invisible at the moment of deploying.

**Checkpoint and resume the build** — the right long-term answer and the
expensive one. It means making `collect_candidates` restartable, which is
another lane's subsystem and a much larger change than this proposal. Listed in
§5 as phase 3, deliberately last.

---

## 3. Proposal: drain the *pipeline*, not the *process*

The insight that makes this tractable: **you cannot drain a 22-minute build
inside a 30-second shutdown, but you can stop new long work from starting and
then wait.**

Drain becomes a state the worker enters *before* the deploy, not something it
does during shutdown.

```
deployer                          refresh-worker
   |                                    |
   |-- set drain_requested (TTL) ------>|
   |                                    |  top of each cycle:
   |                                    |    drain set? -> do NOT start a new
   |                                    |    board build or launch a new sim.
   |                                    |    Cheap ticks continue.
   |                                    |
   |<-- publishes in_flight={...} ------|  each cycle
   |    + acked_drain_at + commit       |
   |                                    |
   |  poll until in_flight is empty     |
   |                                    |
   |-- deploy ------------------------->|  killed while idle: nothing lost
   |                                    |
   |-- clear drain -------------------->|  new process reads clear, resumes
```

### The three pieces

**(a) A drain flag, in the keyvalue store, with a TTL.**
`refresh_state_store` already routes through keyvalue and both workers share it.
For *this* flag sharing is correct — unlike `#405`'s per-service stamp, a drain
request is genuinely about "the deployment", and per-service keys can be added
later if the two workers ever need independent drains.

**The TTL is mandatory, not a nicety.** A drain flag set and never cleared is a
worker that never builds the board again — a permanent outage produced by a
crashed deploy script. TTL of ~45 min (2× the longest observed build) means the
worst case self-heals.

**(b) The worker refuses to START new long work while drained, and says so.**
Two call sites, both already isolated:
- the board build trigger in the intelligence-state loop
- `_run_mlb_sim_tick()` in `run_refresh_worker.py:3208`

Each logs `DRAIN_HOLD stage=<x>` when it declines. In-flight work is **not**
interrupted — it finishes normally.

**(c) The worker publishes what it is doing, positively.**
```json
{"in_flight": {"board_build": true, "mlb_sim": false},
 "acked_drain_at": "...", "commit": "abc1234", "heartbeat": "..."}
```
The deployer waits for `in_flight` to be all-false.

---

## 4. Failure modes, and why each is handled

These are the ways this design breaks, written before it is built rather than
discovered in production. Every one of them is a shape this repo has already
been bitten by.

| failure | consequence if unhandled | handling |
|---|---|---|
| **Drain flag never cleared** (deploy script dies) | refresh-worker never builds the board again — silent permanent outage | TTL on the key, ~45 min. Absence must mean "not draining". |
| **Worker never acks** because the deployed code predates drain support | deployer waits, times out, or worse assumes drained and deploys into a build | The worker publishes `acked_drain_at` **and its commit**. No ack within one cycle → the deployer treats it as UNKNOWN and blocks. *This is tonight's exact lesson: a flag read by code that is not deployed is inert, and `#401` shipped a switch that did nothing for that reason.* |
| **Heartbeat stale** (worker dead or wedged) | deployer reads `in_flight={}` from a dead worker and calls it idle | `heartbeat` must be fresher than 2 cycles. Stale heartbeat = UNKNOWN = block, never "idle". |
| **Two lanes drain at once** | one clears the flag while the other is still deploying | Owner token on the key; only the owner clears it. A second drainer joins rather than overrides. |
| **Drain requested mid-build** | deployer waits the full remaining build | Correct and intended. Report the estimate (`#403`'s `COLLECT_SPAN_EXIT`-derived max) so the human sees the wait up front. |
| **`in_flight` says false but work is running** | deploy kills real work | `in_flight` is set by the same code that launches the work, not inferred. **Verify a suppression by its own positive emission** — see the operational notes. |
| **Drain held so long the slate ends** | board goes stale for the drain window | Cap the drain wait (~30 min) then report and let a human choose. Never auto-deploy on timeout. |

---

## 5. Staged implementation

Ordered so each phase is independently useful and independently abandonable.

**Phase 1 — SIGTERM handler on refresh-worker. Do this first regardless.**
Cheap, no protocol, no coordination. Mirror
`run_live_odds_refresh_worker.py:350`: install `_handle_stop`, and on signal
write a record of what was in flight before dying. Today a killed build leaves
*nothing* — `#388` gave sims death certificates, builds still have none. This
alone turns "the board is stale and nobody knows why" into a log line.

**Phase 2 — the drain protocol above.** Flag + refusal + published state +
a `--drain` mode in `scripts/check_deploy_safety.py`, which is already the tool
everyone runs and already knows how to read build state. Deployers get
`check_deploy_safety.py --drain --wait` instead of a manual gate.

**Phase 3 — checkpoint and resume the board build. ~~The real fix.~~
MEASURED 2026-08-13 AND WITHDRAWN AS SPECIFIED — do not build this.**

The design above assumed a per-sport resume boundary. §6 flagged "how much of
the 13–23 min is per-sport" as the open question that decides whether this is
days or weeks. It was measured before any code was written, from
`candidate_generation` traces already in production logs (`_intel_trace_timed`
prints them to stdout, so no instrumentation was needed):

| sport | n | max_s | median_s |
|---|---|---|---|
| **mlb** | 6 | **1169.0** | **928.5** |
| wnba | 6 | 7.4 | 5.1 |
| soccer | 6 | 2.0 | 1.7 |
| nba | 6 | 0.1 | 0.0 |
| ncaab / nhl / nfl / ncaaf | 6 each | ≤0.05 | 0.0 |

Sum of per-sport maxima = 1304.6s ≈ 21.7 min, which matches the observed build
duration — so this accounts for the whole build.

**~90% of the board build is one sport. Every other sport combined is under ten
seconds.** A per-sport checkpoint would let a restart resume "after wnba" and
save about seven seconds. The premise is wrong, and building it would have
produced a correct, tested mechanism that saved ~5% of the thing it targeted.

**What a real phase 3 would need**: a resume boundary *inside* MLB candidate
generation — plausibly per-game or per-market. **That cannot be specified yet,
because nothing measures below the sport level.** The only timed events in a 3h
window are `candidate_generation` (per sport), `evaluation_bundle` (178.4s) and
`candidate_scoring` (119.4s). MLB's 19.5 minutes is a black box.

**So the unblocking step is instrumentation, not checkpointing**: wrap the stages
inside the `for sport in overview:` loop at `intelligence.py:7349` with the
existing `_intel_trace_timed`, exactly as `candidate_generation` already wraps
the whole iteration at `:7675`. Zero behaviour change, and the next real build
answers where the 19.5 minutes goes.

*Not done here deliberately:* `syndicate/features/intelligence.py` had 26
uncommitted lines from another lane at the time of writing, and tonight produced
three separate incidents of one session committing another's in-flight work.
Whoever picks this up should check `git status` on that file first.

**Revised recommendation: phase 2 is the answer.** Drain converts destroyed work
into waiting, and with ~90% of the cost in a single sport there is no cheap
checkpoint to be had. Revisit only if the waits prove intolerable AND the
instrumentation above shows a boundary inside MLB worth cutting on.

---

## 6. What this does not fix, and open questions

**Does not fix:**
- The board build taking 13–23 minutes (once 77). Drain makes the cost visible
  and schedulable; it does not reduce it.
- refresh-worker being CPU-saturated — 100% of its 2-core limit in 72.4% of
  5-minute buckets, measured 2026-08-12.
- Emergency deploys. A drain that takes 25 minutes is unusable when something is
  actively broken. There must be an explicit `--force` that skips drain, logs
  loudly, and is understood to destroy work.

**Needs measuring before building phase 2:**
1. **Render's actual SIGTERM→SIGKILL grace period on a worker.** Assumed short
   (~30s) and never verified. Measurable directly once phase 1 lands: the
   handler logs on signal, and the gap to the last line is the grace.
2. ~~**How much of the 13–23 min is per-sport.**~~ **ANSWERED 2026-08-13: almost
   none of it.** MLB is ~90% of the build (1169s max) and every other sport
   combined is under 10s. This killed phase 3 as specified — see §5.
3. **Whether the sim can be made resumable at all**, or only restartable.
4. **NEW — where MLB's 19.5 minutes goes.** Nothing measures below the sport
   level, so no resume boundary inside MLB can be specified. This is now the
   only thing standing between here and a real phase 3, and it is a logging
   change, not a design one.

**Explicitly not claimed:** that this is the only design. Moving the board build
off refresh-worker entirely is a real alternative — ownership is already an env
flag (`SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP`) and it has run on
live-odds-worker before. It relocates the problem rather than solving it, but if
one service can be kept deploy-quiet that may be enough. Worth costing before
phase 2 is started.
