# Layer 2 main board — the north star, and how we get there

Written 2026-08-07, immediately after an eleven-hour refresh-worker outage in
which **nine** mechanisms were proposed from source across three sessions and
eight of them were wrong. That failure rate is the most important input to this
plan. It is not a plan for what to build so much as a plan for *how to build it
so the same class of failure cannot recur.*

Supersedes the sequencing in `plan_board_execution_now.md` (W1–W5 there are
folded in below and re-ordered). The product target is unchanged and still lives
in `plan_oddsjam_class_board.md`.

---

## 1. What the board is for

One sentence: **surface every bet where our price is better than the market's,
rank them by how much we should trust that, and prove afterwards whether we were
right.**

Three properties, in dependency order. Each is worthless without the one before.

| | property | means | today |
|---|---|---|---|
| P1 | **Identity** | every row joins to a real market, price, and outcome | mostly done (#221–#232) |
| P2 | **Price truth** | every row carries a real, fresh, no-vig fair value and the book it came from | partial — blanks on one-sided markets |
| P3 | **Proof** | every row eventually settles, and the ranking weights are derived from that | **not started — `settled: 0` of 8,276** |

P3 is the whole product. Without it the board is an opinion with good
typography. `blended_score` currently runs on a *stated prior*
(`_SCORE_SIM_WEIGHT = 0.5`) — a number nobody measured.

---

## 2. The five architectural rules this outage bought us

These are not style preferences. Each one is the direct cause of hours lost.

### R1 — Bound retention, not rate

Six of the eight failed fixes were **rate** fixes: run it less often, cache it,
rate-limit it, parse it once. All six failed. The one that moved the floor
(`#253`) removed **retention**: `mlb/cards.py` held up to 96 full page contexts
in two count-bounded caches, and the floor fell from ~3.1GB to ~0.8GB.

*Applied:* any cache on a worker must be bounded by **bytes or age**, never by
entry count alone. A count bound is a web-shaped bound; it assumes entries are
small and hit rates are real. On the worker both assumptions were false — the
keys were guaranteed to miss (`int(time.time() // 60)` against a ~90s loop), so
the "cache" was a retention buffer with a 0% hit rate that looked identical to a
working one from outside.

**Rule: every worker cache declares a byte budget and logs its evictions.**

### R2 — A guard must sit where the memory is spent

`#249`, `#250`, `#251`, `#252`, `#254` all guarded `_build_candidate_pool` or
the board build. The allocation was already resident *before* that point —
measured, boot 275MB → 2508MB at `pre_source_state_fingerprint`. Every guard was
downstream of the thing it guarded against, which is why the board was correctly
refused with `candidate_count=0` while the container sat at 3.6GB.

**Rule: before adding a guard, produce the checkpoint trace showing the
allocation is downstream of it.**

### R3 — A ceiling that only skips does not bound cost

`SKIP_OVERSIZED_LEDGER_CHUNK` had a 256MB ceiling and correctly skipped 367MB
and 480MB chunks — while a *different* reader with no ceiling read those same
files whole. Same defect as `#75`, in three separate files
(`odds_lifecycle`, `intelligence_evaluation`, `evaluation_settlement`).

**Rule: `read_text()` + `splitlines()` on anything date-sharded or
append-only is a defect. Stream it. A size check decides which files to skip; it
never bounds what reading an accepted one costs.**

### R4 — Claim before you work

The settlement autorun wrote its "I ran" status *after* the work and was
"self-catching-up by construction". A kill mid-run meant the next boot ran it
again — forever. Not the cause of this outage, but it is a latent infinite
crash-loop in any autorun with that shape.

**Rule: any periodic job claims its slot before doing the work, and records
`started` vs `completed` so a SIGKILL leaves evidence.**

### R5 — A log is ordered by time, not by causality

The "14-second window" that three of us reasoned about did not exist:
`post_mlb_sim_tick` is emitted by the worker loop and
`pre_source_state_fingerprint` by the intelligence-state background thread, in
the same process. Two threads' samples interleaved in one stream, read as a call
sequence.

**Rule: every memory checkpoint carries its thread/loop identity. Never infer a
call sequence from log adjacency in a multi-threaded process.**

---

## 3. The plan

### Phase 0 — close out the outage (now, hours)

Exit criteria are measurements, not "looks fine".

- [ ] `#253` holds 60+ minutes with no OOM. Baseline to beat: 21 cycles,
      median 6.0m, **max 14.6m** — a quiet stretch under 14.6m proves nothing.
- [ ] Re-enable `EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN` **with
      `#256` deployed**, and confirm settlement completes without a kill.
- [ ] Remove the `#257` diagnostics once they have answered. They are
      instrumentation, not features.
- [ ] Land `#255` (null identity silently overwrites the wrong ledger record —
      a data-integrity bug, currently filed and unfixed).
- [ ] Re-align the three services. They are on **three different commits**
      spanning `#239`→`#257`; web has been stale ~12h and live-odds-worker ~14h.
      Every cross-service conclusion tonight was tested against a mismatched
      pair.

### Phase 1 — make the envelope structural (1–2 days)

The board cannot be trusted while the process it runs in dies unpredictably.

- **Per-cache byte budgets (R1).** Audit every module-level cache on the worker:
  `mlb/cards.py`, `nba/`, `wnba/`, `odds_lifecycle._JSONL_ROWS_CACHE`,
  `intelligence_state._candidate_pools` / `._snapshots`
  (`_max_snapshots = 12`, deep-copied via `json.loads(json.dumps(...))` on every
  read — the same shape `#253` just fixed, unfixed here). Give each a byte
  budget and an eviction log.
- **Kill the remaining whole-file reads (R3).** `#76`: `odds_events/<date>.jsonl`
  reaches **1.24 GB/day** with nothing rotating it. `odds_history` is pulled
  whole (~28 MB) and is JSON, so it cannot be tail-read — it needs a shape
  change, not a bigger ceiling.
- **Thread-tagged checkpoints (R5).** Cheap, permanent, and would have saved
  most of tonight.
- **One memory contract for the worker**, documented in
  `worker_architecture.md`: what the steady-state floor is, what the transient
  peak may be, and which stages are allowed to allocate above X.

*Exit:* the worker runs a full day with a flat floor and zero kills, and we can
state its steady-state memory as a number.

### Phase 2 — close the feedback loop (2–4 days) — **the highest-value work**

This is P3 and it has never worked. `settled: 0` of 8,276.

- **Verify `#247` in production.** It is shipped and unverified. Watch
  `unmatched_no_key_match` → 0 and `settled` rising. This is the single unlock.
- **Fix settlement scheduling (W2).** It sits 5th of 7 in an `elif` chain and
  can be preempted indefinitely, so its interval is advisory. Fix the
  dispatch, not the interval.
- **Backfill.** 3,716 records have no graded row at all. Ingest prop outcomes
  for historical dates.
- **CLV as the primary metric.** `#213` records the price struck at bet time;
  with settlement working, CLV becomes computable per row, per sport, per market
  family.

*Exit:* a settled-rate above 80% on rows older than 48h, and a CLV distribution
we can plot.

### Phase 3 — price truth with no blanks (3–5 days)

- **Book margin model** for one-sided markets. `batter_home_runs` is 12,409
  rows, **100% `over`** across all 11 books — the other side does not exist in
  the feed. De-vig a lone price using that book's own measured margin from its
  two-sided markets; label it `fair_method: "book_margin_model"` so it is never
  confused with a real two-sided consensus.
- **Sharp anchor.** Add `regions="us,eu"` (Pinnacle) to the **game-line fetch
  only** — ~+5.4% credits on a 2.02M/5M base. Do *not* add it to props: Pinnacle
  barely prices them and it would nearly double spend for nothing. Then make
  `consensus_fair_probability` *prefer* sharp books, or the anchor is one vote
  of twelve.

*Exit:* zero blank fair-value cells on the blotter, every one labelled with its
method.

### Phase 4 — real ranking, then live (1 week+)

- **Retire the prior (W5).** Derive `blended_score`'s weights from Phase 2's
  CLV. **No measurement, no weight.**
- **Then, and only then, live.** Pregame and live are different products:

  | | pregame | live |
  |---|---|---|
  | price half-life | hours | seconds |
  | stale means | normal | **dead** |
  | cost of a stale row | a slightly wrong price | a bet on a pitcher already pulled |

  A live board on an open feedback loop is *confidently wrong in real time*,
  which is strictly worse than being thin. Make pregame excellent first.

---

## 4. Sequencing rules for whoever picks this up

1. **One change per deploy window, pinned by `commitId`.** Render's
   `POST /services/{id}/deploys` takes `{"commitId": "<sha>"}`, so you can push a
   stack and ship only its base. Verify with
   `git merge-base --is-ancestor <later> <deployed>` → must be NO. Deploying
   branch head is how a 40-commit deploy got blamed on its newest commit.
2. **Measure boot-normalised.** The memory floor is a function of
   time-since-boot, and every deploy forces a boot — so *every* fix looks good
   for its first five minutes. Use peak-within-boot and time-to-next-OOM across
   several complete cycles.
3. **State the bar before you look.** Write down the number that would count as
   success, then read the data. Both false "RESOLVED" calls today came from
   reading first.
4. **Confirm the code ran.** `#251` was deployed, measured, failed, and written
   off by three sessions — it had never executed, because another component's
   10s TTL evicted the entries its 300s check asked for.
5. **Prefer serve time to worker time.** `#245`'s pure gate, evaluated at serve
   time, is the model: it cannot go stale in a cached pool and costs the worker
   nothing.
