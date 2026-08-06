# PLAN — the quote layer: surfacing, real timestamps, book attribution, CLV

Answers four asks (2026-08-06). Written after #208–#211, and it depends on them:
#209 created a per-book quote log, #210 backfilled 30 days into it, #211 measured
that best-price shopping is worth **+2.79 ROI points** on an identical bet set.

---

## 0. The one observation the whole plan rests on

All four asks are the same missing object.

A bet has a **price**, and a price is meaningless without three attributes:
**which book**, **what number**, and **when that book last moved it**. Syndicate
has never had that triple as a first-class thing in the read path. Concretely, a
Layer 2 candidate row today is built by `_game_market_recommendation_strings`
([home.py:840](syndicate/blueprints/home.py:840)) out of exactly:

    display_pick, ev_pct, p_win, market_label, selection

There is **no price, no book, and no timestamp in the row contract at all.** So:

- (3) can't label which book has the edge — there is no field to put it in.
- (2) can't show a real timestamp — the only time available is when our loop ran.
- (1) "surface it better" is not a rendering problem. The board is rendering
  everything it is given.
- (4) CLV can't be computed, because CLV is (price at bet) vs (price at close)
  and neither is recorded against a bet.

**So: do not revamp the Layer 2 board.** Its architecture is fine and it is not
the constraint. Extend the *row contract* it consumes. That single change is what
makes 1–3 possible and is a precondition for 4.

The object to add — call it `quote_ref` — already exists in the write path as of
#209. `syndicate/features/shared/odds_book_quotes.py` writes rows carrying
`bookmaker`, `price`, `line`, `snapshot_ts` (**the book's own `last_update`**)
and `captured_at` (**our loop time**), kept deliberately separate. This plan is
almost entirely about *carrying that object forward* rather than building
anything new.

---

## 1. Ask 2 first — real timestamps. It is the cheapest and it gates the rest.

**Status: already captured, nowhere surfaced.**
[odds_book_quotes.py:330](syndicate/features/shared/odds_book_quotes.py:330)
sets `snapshot_ts` from `market.get("last_update") or bookmaker.get("last_update")`.
That is the book's own timestamp, straight from OddsAPI. Every other timestamp in
the system is loop time.

The fix is a contract, not a feature: **two clocks, never conflated.**

| field | meaning | what it answers |
|---|---|---|
| `book_updated_at` | the book last moved this number | "is this price real right now?" |
| `captured_at` | we last looked | "is our data stale?" |

These fail independently and the difference is diagnostic. A price with
`book_updated_at` 4 hours old and `captured_at` 30 seconds old is a **dead
market**, not fresh data — today it renders as fresh. The inverse is our loop
being down while the market moves. One number cannot express both, which is why
today's single timestamp is actively misleading rather than merely incomplete.

**Work**
1. Add both fields to the quote reader's output (they are already on disk).
2. Add `book_age_seconds` / `capture_age_seconds` to the board row.
3. UI: `Book moved 2m ago · checked 30s ago`. Degrade on `book_age`, not
   `capture_age`.
4. Backfill note: rows written before #209 have no `book_updated_at`. Render
   those as unknown — **never fall back to `captured_at`**, which would silently
   recreate the exact conflation being fixed.

---

## 2. Ask 3 — which book has the edge

**Status: the data exists for 5 sports as of #209; nothing reads it.**

`best_price_by_market()` already computes the winner. What is missing is that a
recommendation currently has no notion of *whose* price it was computed against.

**The `quote_ref` block to add to every candidate row:**

```
quote: {
  bookmaker:        "draftkings",
  price:            -108,
  line:             8.5,
  book_updated_at:  "2026-08-06T18:41:02Z",
  captured_at:      "2026-08-06T18:43:30Z",
  price_rank:       1,
  books_quoting:    6,
  consensus_price:  -115,
  edge_vs_consensus_pct: 1.9,
  alternatives: [{book, price}, ...]
}
```

`consensus_price` matters as much as `price`. A best price that is 40 points
clear of every other book is usually a stale or erroneous line, not an edge —
`price_rank: 1, books_quoting: 6` with a tight consensus is a real edge;
`price_rank: 1` alone is not evidence.

**UI, in priority order:**
1. Book chip on every pick: `DK -108` — the single highest-value addition.
2. `best of 6` badge, with hover showing the alternatives.
3. A "you are not on the best price" state for logged bets whose book ≠ best.
4. Sortable board column: *price advantage vs consensus*.

**Why this is worth doing first among the surfacing work:** #211 measured the
cost of not doing it at **+2.79 ROI points**, tight CI [+2.48, +3.13]. That is
the largest single measured improvement available, and it requires no model
change whatsoever.

---

## 3. Ask 1 — surfacing, given the above

With `quote_ref` on the row, surfacing is mostly deletion of ambiguity rather
than new UI:

- **Board row** gains: price, book, best-of-N, two ages. No layout revamp.
- **Candidate ranking** should switch from `ev_pct` computed against one
  arbitrary book to `ev_pct` computed against best available price. This changes
  *which* candidates surface, not just how they look — #211 found 140 bets
  cleared a 3% threshold under best price that did not under single-book, and
  **zero** the other way.
- **New: a "price improvement" strip.** For every live candidate, what you'd gain
  by moving book. This is the one genuinely new surface worth building, because
  it is the only place the +2.79 becomes actionable at bet time rather than
  visible in a backtest.

**Explicitly not doing:** a Layer 2 rewrite. The provider→`game_market_recommendations`
→ feed path already works across seven sports and was hard-won (see the NFL Layer 2
arc in `todo.md`). Changing the row contract is additive; every existing consumer
that ignores `quote` keeps working.

---

## 4. Ask 4 — CLV, settlement, and the portfolio loop

This is the largest piece and it is **broken in a specific, fixable way.**

### What is actually true today (measured on production, 2026-08-06)

`/api/portfolio/summary` returns:

    total_tracked: 5     pending_count: 5     settled_count: 0
    roi: null            avg_clv: null        total_pnl: 0

So: **bets log fine, and nothing ever settles.** Not one position, and CLV is
null across the board.

### Why — three distinct causes, all real

**(a) There are two ledgers and the portfolio only reads one.** This is stated
outright in the code at
[intelligence.py:1919](syndicate/blueprints/intelligence.py:1919):
`/api/intelligence/portfolio-event` writes an evaluation ledger *"the Portfolio
page never reads"*, while `/api/portfolio/bets` writes `data/prediction_ledger.json`,
which is what `/portfolio` renders. `EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN=true`
on refresh-worker settles the **former**. The portfolio's ledger is settled by a
different path (`prediction_reconciliation`, `RECONCILIATION_ENABLE_REFRESH_WORKER_AUTORUN=true`)
— so both autoruns are on, and the portfolio still shows zero settled.

**(b) Reconciliation is starved of input.** It settles by finding result files
matching `RECONCILIATION_PATTERNS`
([prediction_reconciliation.py:28](syndicate/features/prediction_reconciliation.py:28)):
`recon_games_{date}.csv`, `game_results_{date}.json`, `closing_lines_{date}.csv`,
etc. If none exist for a date, nothing settles and no error is raised. Note the
last pattern — **settlement wants a closing-lines file, which is exactly what
#208 established we never captured.**

**(c) CLV has no input even when settlement runs.** `_clv_from_lines`
([prediction_ledger.py:208](syndicate/features/prediction_ledger.py:208))
needs an original line and a closing line. Nothing records the original quote at
bet time, and until #209 nothing could produce a closing line at all.

### The fix, in dependency order

**4.1 — Record the quote at bet time.** `/api/portfolio/bets` and
`record_prediction` must persist the full `quote_ref` (book, price, line, both
timestamps) as the bet's opening price. Without this CLV is permanently
uncomputable for anything logged from now on. **Do this first — it is the only
step that is irreversible if delayed**, because every day without it is another
day of bets that can never have CLV.

**4.2 — Derive closing lines from the quote log.** `closing_quotes()` already
exists (#209). Emit `closing_lines_{date}.csv` in the shape reconciliation
already looks for — no new consumer, no new contract, it just starts finding
files. This is deliberately the lowest-friction option: it makes an existing,
enabled, currently-idle autorun start working.

**4.3 — Emit `game_results_{date}.json`.** From free MLB StatsAPI (already proven
in `scripts/regrade_mlb_game_markets.py`) and each sport's equivalent. This is
the other half of what reconciliation needs.

**4.4 — Collapse the two ledgers, or bridge them.** Recommendation: bridge, don't
merge. Have the evaluation ledger's settlement write results back into
`prediction_ledger.json` by `recommendation_id` (the portfolio's parlay legs
already carry `recommendation_id` — verified in the live payload). Merging two
ledgers with different schemas and different writers is a much larger change with
no additional payoff.

**4.5 — Surface CLV as the primary metric, above ROI.** #211 is the argument:
outcome ROI on ~1,100 bets had CI95 [−7.6%, +3.8%] — **no power** to detect the
edge sizes that matter. The paired price comparison had CI95 [+2.48, +3.13] on
the same data. CLV is the same kind of paired, low-variance instrument. The
portfolio should lead with **beat-the-close rate** and **average CLV**, and treat
ROI as the noisy secondary number it demonstrably is.

**4.6 — Per-book realized price quality.** Once bets carry a book, track whether
the book actually bet was the best available. This closes the loop on ask 3 and
turns the +2.79 from a backtest number into an operational one.

---

## 5. Ordering, and what I would do first

| # | work | unblocks | size |
|---|---|---|---|
| 1 | `quote_ref` on the row contract | asks 1, 2, 3 | S |
| 2 | Record quote at bet time (4.1) | all of CLV, forever | S |
| 3 | Book chip + two clocks in UI | asks 2, 3 visible | S |
| 4 | `closing_lines_{date}.csv` from quote log (4.2) | settlement starts | M |
| 5 | `game_results_{date}.json` (4.3) | settlement completes | M |
| 6 | Ledger bridge (4.4) | portfolio shows settled | M |
| 7 | Rank candidates on best price | changes what surfaces | M |
| 8 | CLV-first portfolio + price-improvement strip | asks 1, 4 complete | L |

**Items 1 and 2 are small and should go first**, in that order. Item 2
especially: it is the only one where delay causes permanent data loss, which is
the same mistake #208 documented — the books were not lost because anyone decided
to discard them, they were lost because nothing wrote them down.

## 6. Caveats worth stating up front

- The #209 capture fix is **committed but not yet deployed** to Render
  (auto-deploy is off; deploying kills in-flight sims). Nothing in section 4 can
  produce live data until it ships. The backfilled 30 days are usable immediately.
- Per-book quotes exist for **five** sports (MLB, NFL ×2, NCAAF) plus the three
  that were already correct (soccer, NHL, NCAAB). **NBA/WNBA are class B** —
  captured but not routed — and need the routing fix before any of this works for
  basketball.
- Every number in this document that came from a single measurement is marked
  with where it came from. The `settled_count: 0` reading is one production call
  at one instant; it should be re-checked after a settlement window before anyone
  concludes the autoruns are broken rather than idle.
