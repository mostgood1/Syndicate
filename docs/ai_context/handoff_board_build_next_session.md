# Handoff — build the Layer 2 board (pregame + live)

**Start here.** Then read, in this order:

1. `postmortem_2026_08_07_board_session.md` — what the last session broke and
   got wrong. Read it so you do not repeat it. It is short.
2. `plan_board_execution_now.md` — the work list (W1–W5).
3. `plan_oddsjam_class_board.md` — the north star: EV, CLV, arbitrage,
   mispricing, and the sim edge, with the measured numbers behind each.
4. `handoff_refresh_worker_oom.md` — the memory envelope you are working in.
5. `runtime_execution_model.md` + `worker_architecture.md` — **read these before
   adding any worker work.** Not reading them is what caused the outage.

---

## State of production right now (2026-08-07 ~04:10Z)

- **refresh-worker: reverted to its known-good artifact behaviour.** Commits
  `94600923`, `d5028810`, `0d7c839c` reverted `#241`, `#241 follow-up` and
  `#237`. Confirm `BOOTED` frequency is back to ~0/hour before doing anything
  else — the last session's changes caused a ~3 minute restart loop.
- `SYNDICATE_ARTIFACT_REFRESH_INTERVAL_SECONDS=120` is set on refresh-worker but
  now has **no reader** (its consumer was reverted). Harmless; remove it.
- `EVALUATION_SETTLEMENT_REFRESH_INTERVAL_SECONDS=3600` **is** live and does
  have a reader — it switches settlement from once-daily to hourly. Decide
  whether to keep it.
- The board serves: **14 opportunity / 20 dead / 166 watchlist** of 200 rows.
- **`settled: 0` of 8,276 ledger records.** The feedback loop has never closed.

---

## The one thing to do first

**Verify `#247`.** It is shipped, unverified, and is the likely unlock for the
entire feedback loop.

Settlement's market gate compared free-text families:

```
_market_family("pitcher outs") -> "props"      (record side, board label)
_market_family("outs")         -> "outs"       (graded row, stat label)
                                  never equal -> every prop match blocked
```

That is 4,560 of 8,276 unmatched. `#247` makes both sides compare
`canonical_market_key`. **Measure `unmatched_no_key_match` after the next
settlement run.** If it drops toward zero and `settled` rises, the loop closes
and everything downstream (CLV, calibration, real ranking weights) becomes
possible.

Watch: `GET /api/ops/evaluation-settlement/status` — but remember it reports the
**last thing refresh-worker wrote**, not live state (§2.3 of the post-mortem).

---

## The blocker behind the blocker

Even with `#247` correct, settlement may not run often enough to matter:
`run_refresh_worker.py` dispatches autoruns through an **`elif` chain**, one per
cycle:

```
1 mlb_refresh  2 weekly_sports  3 soccer_weekly  4 reconciliation
5 evaluation_settlement   6 season_projections   7 preseason
```

Settlement is **5th of 7** and can be preempted indefinitely, so its interval is
advisory. This is W2 in the plan. Fix the scheduling, not the interval.

---

## What is already built and working (do not rebuild)

- **`opportunity_gate.py`** — the single eligibility rule (identity → market
  posted → not final → book clock fresh → fair method). Pure, and **runs at
  serve time** so its verdict cannot go stale in a cached pool. Every consumer
  reads its verdict; nothing re-derives a lane. Keep this shape.
- **`opportunity_signals.py`** — no-vig fair value, hold, EV, arbitrage,
  low-hold, model edge, blended score. Note `hold = (total-1)/total`, not
  `total-1`; de-vig happens **within a book**, never across best prices.
- **`quote_enrichment.py`** — attaches quotes, fair value, score, delegates the
  lane to the gate.
- The blotter (`intelligence.html`) has Book / Fair / EV / Age columns and a
  lane split (Opportunities / Watchlist / Dead / All). **The blotter is the
  default above 900px** — verify there, not on cards.

---

## The remaining work, in order

**W1 — headroom.** `#248` (tail reads for append-only shards, 90 MB → KB) is
shipped and verified; it makes the *existing* repair path cheaper and adds no
periodic work. Still open: `#76` — `odds_events/<date>.jsonl` reaches **1.24 GB
in a day** and nothing rotates it. `odds_history` is still pulled whole (~28 MB)
and is JSON, so it cannot be tail-read; it needs a different shape.

**W2 — settlement cadence.** Take it out of position 5 of the `elif` chain.

**W3 — close the loop.** Verify `#247`/`#246`; ingest prop outcomes for
historical dates (3,716 records have no graded row at all).

**W4 — fair value with no blanks.** Two independent tracks:
- *Margin model* for one-sided markets. `batter_home_runs` is **12,409 rows,
  100% `over`** across all 11 books — the other side is not in the feed and
  cannot be captured. De-vig a lone price using that book's own measured margin
  from its two-sided markets; label `fair_method: "book_margin_model"`. This is
  the only thing that fills those cells.
- *Sharp anchor*: add `regions="us,eu"` (Pinnacle, key `pinnacle`) to the
  **game-line fetch only** — ~+5.4% credits on a 2.02M/5M base. Adding it to
  props would nearly double spend for almost nothing, because Pinnacle barely
  prices player props. Then make `consensus_fair_probability` *prefer* sharp
  books, or the anchor is just one vote of twelve.

**W5 — real ranking weights.** `blended_score` currently uses a stated prior
(`_SCORE_SIM_WEIGHT = 0.5`, book-confidence and freshness curves). Derive them
from W3's CLV and retire the prior.

---

## Pregame vs live — they are different products

| | pregame | live |
|---|---|---|
| price half-life | hours | seconds to minutes |
| stale means | normal (books post early and sit) | **dead** (>900s on an in-progress game) |
| fair value | full two-sided consensus | often one-sided; markets suspend constantly |
| cost of a stale row | a slightly wrong price | **a bet on a pitcher already pulled** |

Recommendation: make pregame genuinely excellent through W4 first. A live board
on an open feedback loop is confidently wrong in real time, which is worse than
being thin.

---

## Non-negotiables

1. **A rate is a measurement; a count is an anecdote.** Compute the denominator.
   Check your own deploys before calling anything systemic.
2. **A status artifact is not live state.**
3. **New periodic work on refresh-worker is never free** — ~1.4 GB headroom, one
   serial process. Prefer serve time; the gate is the model.
4. **Verify on the blotter at desktop width**, not the card view, not the payload.
5. **Absent must never render as a value.**
6. **One rule, one place.** Writing the same rule twice means the design is wrong.
7. **No measurement, no weight.**
