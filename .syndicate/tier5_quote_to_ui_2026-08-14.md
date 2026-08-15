# TIER 5 / Deliverable 2 — quote change → UI reflects it, measured

Measured against **production** 2026-08-14 21:37–22:0x CDT (2026-08-15
02:37–03:0xZ), during a full live MLB slate. Read-only. Nothing deployed.

Deployed commits, re-read in the same step: web `a86eb4ed`, refresh-worker
`548ded38`, live-odds-worker `ccd10349`.

---

## First, the prerequisite the brief asked about

**The per-sport pregame relaunch cooldown (`ea8fad58`) is NOT deployed.**
Checked by reading the deployed trees, not by ancestry alone — on both
`ccd10349` and `548ded38` the gate is still

```python
def _pregame_relaunch_blocked(*, now_epoch: float, date_str: str) -> bool:
```

with no `sports` parameter. (`ea8fad58` is a rebase of the plan's `9ec20a06`
and *is* an ancestor of `origin/main`, which is why an ancestry-only check
would have said "shipped". `autoDeploy` is off; being on `main` ships nothing.)

**But the 121.6-minute floor does not apply to this measurement anyway, and
that is the more important finding.** On the deployed tree the cooldown is
reached only through a phase guard:

```python
effective_phase = ("live" if any_live else "pregame") if adaptive_enabled else ...
...
if not skip_launch and effective_phase == "pregame" and _pregame_relaunch_blocked(...):
```

`latest_tick` carries `adaptive: true, anyLive: true, phase: "live"`. **While any
game is live the 1800s cooldown is bypassed entirely** and the tick interval
becomes `SYNDICATE_LIVE_ODDS_REFRESH_INTERVAL_SECONDS = 60`.

So `0.1` is a prerequisite for the **pregame** board's freshness. It is **not** a
prerequisite for the live-product measurement, and Tier 5 should stop treating
it as a blocker on this number.

### The real cadence, all three regimes, measured

Every distinct `captured_at` minute in
`mlb_source/tracking/book_quotes/2026-08-14.jsonl` (371,567 rows, streamed from
web via `/api/ops/artifacts/stream` — the artifact, not the logs):

| window (UTC) | slate state | gap between captures |
|---|---|---|
| 07:03 → 15:10 | pregame, nothing live | **121, 121, 123, 121 min** |
| 16:20 → 18:25 | first games start | 70, 61, 64 min |
| 18:36 → 20:54 | slate ramping | **11–12 min** |
| 21:48 → 02:53 | full live slate | **1 min, essentially continuous** |

The 121.6-minute figure is **exact and reproduced** — and it is the
*empty-slate pregame* regime only. The same pipeline samples **122× faster**
once games are live. Any statement of the form "the odds are sampled every two
hours" is true for eight hours a day and wrong for the rest.

---

## The number

**End-to-end = (age of the freshest quote when the board was built) + (age of
the board artifact when it was served).** Both components are in the served
payload; the decomposition was validated against an absolute book timestamp
(row `updated_at` 20:54:00Z, `age_seconds` 20208.8, `generated_at` 02:31:10Z,
`server_time` 02:37:04Z → 22s residual), which is what establishes that
`age_seconds` is stamped at build time and not at serve time.

### Layer 1 — the research surface (`/api/board/book-grid?sport=mlb`)

15 usable samples at 60s, 4 board builds, no gaps:

```
build gaps           10.8, 5.1, 4.2 min
stage 1 (quote→build)  60.5 / 102.8 / 114.6 / 401.5 s   (one value per build)
end-to-end           min 143 s (2.4 min)
                     p50 451 s (7.5 min)
                     max 698 s (11.6 min)
```

**Layer 1's answer: a quote change reaches the served research surface in
2.4 min best case, 7.5 min typical, 11.6 min worst — a sawtooth whose period is
the board rebuild interval, not the fetch interval.**

Network latency is not a term: client-minus-server was −0.3 to −0.7 s.

### Layer 2 — the curated product board (`/api/board/layer2-shortlist`)

This is the surface the product actually is, and it is a different number by an
order of magnitude. The payload carries its own build stamp, `written_at`:

```
written_at   2026-08-15T01:53:44Z   — unchanged across every sample
artifact age 3504 s → 3866 s, still climbing when the window closed
end-to-end   3660 s → 4022 s   = 61.0 to 67.0 minutes, monotonic
```

`quote_seen_age_seconds` was pinned at exactly 156.0 s in every sample, which is
the tell: the artifact is frozen, so its quote ages are frozen with it. **No
rebuild was observed in the whole window** — this is a lower bound on the
staleness, not a measured sawtooth, because the stale period had not ended.

**CONFOUND, stated plainly, and it means this number is not a baseline.**
refresh-worker took three deploys inside the preceding 31 minutes — `ae7318a2`
01:58:39Z, `934b3b81` 02:10:28Z, `548ded38` 02:29:39Z — from the concurrent
`#435` memory investigation. Every one reboots the worker. Supporting reads:

- `LAYER2_FAST_REFRESH` on refresh-worker since 01:30Z: **0**
- `MEMORY_GUARD_ABORT` in the same window: **0** — so it is *not* the memory
  guard refusing, which is the known failure mode; it is simply not running
- the worker is alive and healthy right now (02:51Z, `memory_anon_mb` 1161,
  headroom 2433 MB) and building cards

So: Layer 1's number is clean and Layer 2's is not. What tonight establishes
about Layer 2 is the **shape** — the product board's staleness is governed by
the Layer 2 rebuild, which can and did stop for an hour without any alarm
firing — not the 61-minute value.

---

## What this makes knowable about the movement family

The plan says movement work is "computing on a signal sampled roughly every two
hours." **That is wrong in both directions, and the real constraint is a third
thing neither framing names.**

From `/api/ops/odds-history/inspect?sport=mlb&date=2026-08-14`, 3,582 markets:

- mean sampling interval within the retained history: **p50 1.0 min**
  (live 0.9, pregame 1.0), not 2 hours
- but `history_points` is **capped at 20** — 3,130 of 3,582 markets sit exactly
  at the cap — by `_ODDS_HISTORY_LIMIT` in
  `syndicate/features/shared/odds_refresh_tracking.py:40` (env-tunable via
  `SYNDICATE_ODDS_HISTORY_LIMIT`, **not set on any of the three services**)
- so the retained window is **span p50 17.8 min**, and the code's own comment
  already concedes the consequence: *"narrower than the steam detector's stated
  45-min window for hot markets"*

**The operative defect is not the sampling rate. It is that the buffer holds 20
points, so at the live cadence a movement calculation sees ~18 minutes and is
structurally blind to whether the previous sweep was 1 minute or 2 hours
earlier.** A pregame→live transition — the single largest price move of the day
— falls out of the buffer within 20 minutes of the slate going live.

`movement_velocity` and the steam detector should be re-examined against
`_ODDS_HISTORY_LIMIT`, not against the fetch cadence. Raising it is one env var,
against the 8 MB keyvalue payload ceiling that forced it to 20 in the first
place — so it is a real trade, not a free win.

---

## OPEN DISCREPANCY — flagged, not resolved, and not mine to close

`state.md` records that **live-odds-worker carries
`SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP='false'`** and that *"the service named
for odds is not doing the odds work; the 4GiB memory-pressured worker is."*

Read from the Render env API this session:

| service | `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP` | `SYNDICATE_MLB_REFRESH_TICK_OWNER` |
|---|---|---|
| live-odds-worker | **`true`** | **`true`** |
| refresh-worker | `false` | `false` |
| web | `false` | — |

That is the **opposite** of what the ledger says, and the 02:35:20Z tick wrote
`refresh_status_latest__live-odds-worker.json`, consistent with the env.

**But** `ODDS_SWEEP_OUTCOME` since 02:00Z: **refresh-worker 16, live-odds-worker
0** — consistent with the ledger. The emitter is in `live_refresh_loop.py`
(lines 4100/4117) and is reachable from the board-build sweep as well as from
the loop tick, so both services emitting it is not a contradiction in itself.

I am **not** recording a correction to `state.md` on this. Either the env moved
since the ledger entry (env changes carry no diff — the `which service runs the
code` rule) or the two signals measure different loops. Resolving it needs the
board-build loop, which this session was instructed not to touch, and it
overlaps the live `#435` investigation. **Flagged so nobody reads the ledger's
line as current without re-checking the env first.**

---

## Cost context for the decision

From `/api/ops/oddsapi/quota` (aggregates since 2026-07-28, i.e. 18 days,
bucketed by hour-of-day — *not* a 24-hour total):

- cumulative **1,691,686 credits / 233,947 calls**; baseline `used` 1,608,644
- ≈ 94k credits/day → against the 5M cap in
  `project_oddsapi_call_budget`, roughly **53 days of runway from 07-28**
  (the API header's "13,391,356 remaining" is the number that memory says not
  to believe)
- live-slate hours (22–02Z) burn **187,915 credits/hour** against **14,116** in
  the quiet hours — **13.3×**

Live capability is already the expensive regime. More of it is a budget
decision, not only an engineering one.

---

## Sampling floor, stated so the number is interpretable

- **Layer 1, live slate:** floor is the **board rebuild interval** (4.2–10.8 min
  observed), *not* the fetch cadence (60 s). Quote capture is 6–10× faster than
  the board can consume it.
- **Layer 1, pregame:** floor is the **121.6-minute rotation**, unchanged, and
  `0.1` is the fix for it.
- **Layer 2:** floor is the Layer 2 rebuild, which was not running tonight.
  Ledger baselines for comparison: 19.6 min longest gap after `#387`, 104.7 min
  before it. Tonight: ≥60 min, with three deploys as a confound.
- **20 samples over 18 minutes**, one live MLB slate, one sport. A pregame-only
  window and a clean (deploy-free) Layer 2 window are both still unmeasured.

---

## For the product decision — what the measurement says, not what to choose

**If the answer is "build the live game-line projection":** latency is not the
obstacle. 2.4–11.6 min end-to-end on Layer 1 during a live slate is a workable
budget for a game-line product, and the fetch side already runs at 60 s with
headroom. The two things that would have to be fixed first are on the *board
rebuild* side (Layer 2 reliability) and the *history depth* side
(`_ODDS_HISTORY_LIMIT`), plus the OddsAPI runway above. Deliverable 1 also
records that a working live projector already exists in soccer
(`soccer/features/live_lens.py`), unwired — so this is not green-field
everywhere.

**If the answer is "pregame-first with a prop-only live tier":** then the
121.6-minute pregame cadence becomes the product's defining number rather than
an embarrassment, `0.1` becomes the highest-value deploy in the program, and
Deliverable 1's severed MLB prop link (`mlb/live_lens.py:1109`) is the whole
live tier — currently returning 0 edges on 989 live rows.

**Either way, one thing should be fixed regardless of the decision:** the 5 live
NFL model edges now on the shortlist, priced from a pregame full-game total
against a Q4 market, because `nfl_game_projections.py` does not import
`live_edge_policy`. That is wrong under both options. See Deliverable 1 §B.
