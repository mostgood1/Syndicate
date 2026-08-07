# The board: what to build now

**This supersedes the analysis in `plan_layer2_board_end_to_end.md`.** That
document diagnosed; this one is the work list. Read this one to act.

Built from what the repo already knows — `handoff_refresh_worker_oom.md`,
`syndicate_world_class_execution_backlog.md`, `runtime_execution_model.md`,
`worker_architecture.md`, `todo.md` #76 — plus production measurement taken
2026-08-06/07. Nothing here re-derives what those already establish.

---

## The finding that reorders everything

The execution backlog marks **Phase 5 "Close the evaluation loop" as Completed**
and **Phase 6 "Harden ops and runtime boundaries" as Completed**. Production
disagrees:

| Backlog says | Production measures | Delta |
|---|---|---|
| Phase 5 evaluation loop **Completed** | 8,276 ledger records, **0 settled**, 0 matched | the loop has never closed |
| Phase 6 runtime boundaries **Completed** | worker restart loop at ~3 min under added load; settlement is 5th of 7 in an `elif` chain | no scheduling or memory guarantee |
| Phase 3 odds management **Completed** | 11 books, no sharp anchor, `batter_home_runs` 12,409 rows **100% one-sided** | a whole market class cannot be priced fair |

Phases were marked complete on *code shipped and tests passing*, never on a
measured production outcome. That is the same trap `todo.md` records as
"closed ≠ shipped", one level up: **closed ≠ working**.

So the plan is not a new phase list. It is a short punch list that closes the
gap between documented and measured, in dependency order, with every item
costed against the worker's memory envelope.

---

## The budget every item spends from

From `handoff_refresh_worker_oom.md` (the 2026-07-26 OOM, already root-caused
and fixed):

- refresh-worker plateaus at **2.65–2.70 GB of 4 GB** — **~1.4 GB headroom**
- `odds_events/<date>.jsonl` reached **1.24 GB in a single day**; nothing prunes
  or rotates it (**#76, still open**)
- the plateau climbs during MLB games 0–11

**There is no slack.** My own #241 added a 74 MB + 40 MB stream every 120 s and
put the worker into a ~3-minute restart loop within the hour. Every item below
states its worker cost, and W1 exists to buy headroom before anything else
spends it.

---

## W1 — Reclaim worker headroom  *(blocks everything else)*

**Cost: negative. This is the only item that gives memory back.**

1. **#76: rotate and prune `odds_events`.** 1.24 GB/day, unbounded, already
   filed. Daily rotation plus a retention window. The read path is already
   streamed (`5181ed3d`), so this is purely about what accumulates on disk and
   in page cache.
2. **Stop re-streaming the whole quote shard.** `book_quotes/<date>.jsonl` is
   **append-only**, so re-fetching 74 MB to learn about the last few KB is pure
   waste. Fetch the tail: keep a byte offset per shard, send `Range:
   bytes=<offset>-`, append locally. Falls back to a full pull when the remote
   is smaller than the offset (rotation/rewrite).
   - `SYNDICATE_ARTIFACT_REFRESH_INTERVAL_SECONDS=600` is the current
     **mitigation, not the fix** — it was set at 03:09 to stop the restart loop.
3. Keep the `#241` refresh in the loop, but on tail reads it becomes cheap
   enough to run at its intended cadence again.

**Exit:** zero unexplained `BOOTED` over 2 hours across a live slate; container
memory ≤ 60%; the artifact refresh returns to ≤ 120 s without regression.

---

## W2 — Give settlement a cadence it cannot be starved out of

**Cost: near-zero — it is a scheduling change, not new work.**

`run_refresh_worker.py` dispatches autoruns through an `elif` chain, one per
cycle:

```
1 mlb_refresh  2 weekly_sports  3 soccer_weekly  4 reconciliation
5 evaluation_settlement   6 season_projections   7 preseason
```

Settlement is 5th of 7 — four autoruns can preempt it indefinitely, so its
interval is advisory at best. Either lift it out of the chain into its own
time-gated block, or make the chain fair (round-robin among due autoruns rather
than first-due-wins).

**Exit:** settlement observed running at its configured cadence for 6
consecutive hours regardless of what else was due.

---

## W3 — Close the loop

**Cost: settlement already runs; this is correctness, not load.**

1. **#247 (shipped, unverified).** Settlement's market gate mapped
   `"pitcher outs" → "props"` and `"outs" → "outs"` and blocked every correct
   prop match — 4,560 of 8,276. Now compares canonical keys.
   **Verify:** `unmatched_no_key_match` 4,560 → <100.
2. **Ingest prop outcomes.** 3,716 records have no graded row at all; graded
   rows that exist are `moneyline` only for historical dates. Today's slate
   emits 192 graded rows, so the grader works — the gap is historical dates
   whose inputs were never produced.
3. **#246 (shipped, unverified).** `settlement_inputs/*` was not allowlisted, so
   every emitted `closing_lines`/`finals` file was refused at the service
   boundary. Verify they now land on web.

**Exit:** `settled > 0` and rising daily; CLV computed for ≥500 settled records.

---

## W4 — Fair value with no blanks

**Cost: one extra region on game-line calls only (~+5.4% credits on a 2.02M/5M
base). Props stay `regions=us`.**

1. **Margin model for one-sided markets.** `batter_home_runs` is 12,409 rows,
   100% `over`, from all 11 books — the other side is not in the feed, so it
   cannot be captured. De-vig a lone price using that book's own measured margin
   from its two-sided markets. Label `fair_method: "book_margin_model"` so it is
   never confused with a true two-sided fair. This is the only thing that fills
   those cells.
2. **Sharp anchor on game lines.** Add `regions="us,eu"` (Pinnacle, key
   `pinnacle`) to the game-line fetch **only**. Then make
   `consensus_fair_probability` *prefer* sharp books — otherwise we have paid
   for an anchor and used it as one vote of twelve.

**Exit:** `fair_unavailable` = 0 on the opportunity lane; every fair price
carries a `fair_method`.

---

## W5 — Rank by measured weights

**Cost: none — it replaces constants.**

`blended_score` currently uses a **stated prior** (`_SCORE_SIM_WEIGHT = 0.5`,
book-confidence and freshness curves). Once W3 produces CLV per signal bucket,
derive the weights and retire the prior. Until then the code says it is a prior,
which is the honest state.

**Exit:** weights cite the CLV that set them.

---

## Order, and why

```
W1 headroom ──► W2 cadence ──► W3 close the loop ──► W5 real weights
                                      │
                                      └──► W4 fair value (parallel, independent)
```

W1 first because a restarting worker builds no boards, settles no bets and runs
no sims — and because every later item spends from the envelope W1 refills.
W4 is independent of the loop and can run in parallel once W1 lands.

---

## Invariants (from `plan_layer2_board_end_to_end.md` §6, kept short)

1. One gate decides eligibility (`opportunity_gate`), pure, run at serve time.
2. One identity: `canonical_market_key` on every join — pricing *and* settlement.
3. Every number carries provenance (`fair_method`, gate `reasons`, score
   components).
4. Absent never renders as a value — `Number(null)` is `0` and `0` is finite.
5. Freshness judged on the **book** clock.
6. No measurement, no weight.
7. A rate is a measurement; a count is an anecdote — check successes and your
   own deploys before calling anything systemic.
8. **New periodic worker work is never free.** State its cost against the
   ~1.4 GB headroom, or do it at serve time instead.

---

## Status right now

| item | state |
|---|---|
| #245 gate (one eligibility rule, serve-time) | shipped, verified live |
| #246 settlement inputs allowlisted | shipped, unverified |
| #247 settlement market gate | shipped, unverified |
| W1 headroom | **mitigated only** (600 s backoff); tail reads not built |
| W2 cadence | not started |
| W3 close the loop | blocked on W2 |
| W4 fair value | not started |
