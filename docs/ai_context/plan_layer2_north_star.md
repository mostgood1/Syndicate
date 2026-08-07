# The board family — Layer 1 (research) and Layer 2 (recommendations)

Written 2026-08-07. Supersedes the first draft of this file, which led with the
memory envelope and was mis-weighted: the look and feel is broadly right, the
**data pipeline's correctness and timeliness** is the problem, and the product
is not one board but a **family** of them.

Reference surfaces the user has named as the target: OddsJam's per-book grid and
its +EV / Low-Hold / Arbitrage tables, and player-props.com's projection+edge
view. Our differentiator over all of them is the **sim**.

---

## 1. The split

| | **Layer 1 — research** | **Layer 2 — recommendations** |
|---|---|---|
| question | "show me everything, let me look" | "what should I bet" |
| scope | **by sport, by day** — the full portfolio | **cross-sport, consolidated** |
| completeness | every market, every line, no quality filter | only what survives the gate |
| opinion | none — it presents, it does not rank | ranked, scored, opinionated |
| consolidates | betting lines + sim + advanced analytics | betting logic + sim factor |
| failure mode | missing a market | recommending a bad bet |

**Layer 1 is a microscope. Layer 2 is a shortlist.** A row can be absent from
Layer 2 and must still be present in Layer 1.

---

## 2. The five boards

### Layer 1

**L1-A — Book view.** The OddsJam grid. Every market for a sport/day, one
**column per book**, best price highlighted, market-family tabs (Main Markets /
Moneyline / Run Line / Total Runs / 1st Half …), live-state chip per row
("BOT 2"), `updated` per quote.

**L1-B — Advanced data view.** The player-props shape, per betting line:
`Line | Over | Under | Projected | Edge Proj | Edge Eff% | Avg/G | Edge AVG |
Injuries | rank columns | Min. Proj | L5 | L10`. This is where the sim and the
advanced analytics sit next to the market price. **This view is the reason we
exist** — OddsJam cannot show it.

### Layer 2

**L2-A — Best bets.** Ranked by the blended score: EV + sim edge + hold +
book confidence + freshness. The consolidated recommendation surface.

**L2-B — Arbitrage.** `PERCENT | REC. BET SIZE | EVENT | MARKET | BETS | BOOKS |
NO-VIG ODDS | WIDTH | UPDATED`. Requires two sides across *different* books,
simultaneously.

**L2-C — Low hold.** Same shape, ranked by hold rather than guaranteed profit.

---

## 3. One row contract, five views — non-negotiable

If we build five pipelines we will get five boards that disagree, and we will
spend the next month reconciling them. Today's lesson: **one rule, one place.**

Every board is a **projection or a filter over one canonical row**:

```
market_row = {
  identity:   sport, event_id, commence_time, home/away, player_name,
              market_key (canonical), selection, line, segment
  prices:     { book: {price, snapshot_ts} }        <- ALL books, not "best"
  derived:    best_price, best_book, books_quoting,
              no_vig_fair, hold, width, ev_pct, arb_pct
  sim:        projection, edge_proj, edge_eff_pct, confidence
  analytics:  avg_g, l5, l10, ranks, injuries
  state:      live/pregame, game_state, suspended, age_seconds
}
```

- **L1-A** = the row, pivoted on `prices`.
- **L1-B** = the row, pivoted on `sim` + `analytics`.
- **L2-A** = rows passing `opportunity_gate`, ranked by `blended_score`.
- **L2-B** = rows where `arb_pct > 0` across books.
- **L2-C** = rows ranked ascending by `hold`.

`opportunity_gate.py` (#245) already owns eligibility and runs at **serve time**
so it cannot go stale in a cached pool. `opportunity_signals.py` (#238/#243)
already computes no-vig, hold, EV, arb, low-hold and the blended score. Those
two are the Layer 2 selectors and they exist. **The gap is Layer 1 and the
substrate, not Layer 2's logic.**

---

## 4. What we measured against this (2026-07-29 MLB shard, 39,370 rows)

```
DISTINCT BOOKS: 11
  draftkings 7,080 · betmgm 6,650 · bovada 4,021 · betrivers 3,955
  williamhill_us 3,861 · mybookieag 3,603 · betonlineag 3,541
  fanatics 2,404 · fanduel 2,353 · lowvig 1,018 · betus 884

GRID WIDTH — books per (event, market, selection, line):
  1,002 of 1,463 selections (68.5%) have 3+ books   -> grid is buildable TODAY
    282 selections are single-book                  -> blank no-vig/width

TWO-SIDED WITHIN ONE BOOK (needed for no-vig + width):
  3,045 of 4,450 (68.4%)

FRESHNESS: snapshot_ts, 78 distinct stamps across 34 hours ~= one per 26 min
```

Three conclusions, each with a direct consequence:

1. **L1-A is a presentation gap, not a capture gap.** We capture 11 books and
   render one "best price". The full grid is available from data already on
   disk. This is the largest visible win available and it costs the worker
   nothing — it is a serve-time pivot.
2. **Timeliness is the real defect.** ~26 minutes between snapshots is
   defensible pregame and *fatal* live: the OddsJam live board moves every
   pitch. A 26-minute-old live price is not stale, it is fiction. Showing an
   honest `UPDATED` column will make this obvious and it should.
3. **~31% of selections will show blank no-vig/width** — single-book or
   one-sided. `batter_home_runs` is 12,409 rows, **100% `over`** across all 11
   books; the other side is not in the feed. Only the margin model fills those.

---

## 5. Sequence

Ordered by what unblocks a **column**, not by subsystem.

### S1 — L1-A, the book grid (days, serve-time only)
Pivot `book_quotes` into per-book columns. Best-price highlight, `books_quoting`,
width, no-vig where two-sided, honest `updated`. Market-family tabs off
`canonical_market_key` (#224/#247 already thread it end to end).
*Exit:* a sport/day grid that matches the OddsJam screenshot, with real books.

### S2 — cadence, split pregame from live
26 min pregame is acceptable; live needs sub-minute. **Live capture belongs on
live-odds-worker, not refresh-worker** — the two have different budgets and one
serial process each. Do not add a live loop to the worker that just stopped
dying.
*Exit:* a live row's `age_seconds` is under a minute; pregame under 5.

### S3 — L1-B, the advanced view (the differentiator)
Join sim projections + advanced analytics onto the same rows: `Projected`,
`Edge Proj`, `Edge Eff%`, `Avg/G`, `L5/L10`, injuries, ranks.
*Exit:* every prop row on a slate carries a projection or an explicit reason it
does not.

### S4 — fill the blanks
Book-margin model for one-sided markets, labelled
`fair_method: "book_margin_model"` so it is never confused with a true two-sided
consensus. Pinnacle (`regions="us,eu"`) on the **game-line fetch only** —
~+5.4% credits on a 2.02M/5M base; adding it to props would nearly double spend
for almost nothing.
*Exit:* no blank no-vig cells that are not explicitly labelled.

### S5 — L2-B and L2-C (arb + low hold)
Mostly exist in `opportunity_signals`. The hard part is **simultaneity**:
requiring it dropped 88% of raw arb pairs, and the honest count went 716 -> ~3.
Enforce same-snapshot pairing or the number is fiction.
*Exit:* an arb row can be acted on — both legs still live at the same instant.

### S6 — prove L2-A
`settled: 0` of 8,276. Until settlement works, `blended_score` runs on a stated
prior (`_SCORE_SIM_WEIGHT = 0.5`) that nobody measured. Verify #247, fix
settlement's dispatch (5th of 7 in an `elif` chain, so its interval is
advisory), backfill 3,716 ungraded records, then derive the weights from CLV.
*Exit:* **no measurement, no weight.**

---

## 6. Constraints carried over from the 2026-08-07 outage

Not a phase. Constraints on every step above.

- **S1 and S3 are serve-time pivots and must stay that way.** They cost the
  worker nothing. `opportunity_gate` is the model to copy.
- **Bound retention, not rate.** Six rate fixes failed that night; the one
  retention fix (#253, ≤96 cached page contexts -> ≤2) dropped the floor from
  ~3.1GB to ~0.8GB. Any worker cache gets a **byte** budget and an eviction log,
  never a bare entry count.
- **Stream anything date-sharded or append-only.** `read_text()` +
  `splitlines()` was the same defect in three separate files. A size ceiling
  decides what to *skip*; it never bounds what reading an accepted file costs.
- **Claim before you work.** Status written after the work, plus self-catch-up,
  is a latent infinite crash loop in any autorun.
- **One change per deploy window, pinned by `commitId`;** measure
  boot-normalised (the floor is a function of time-since-boot and every deploy
  reboots, so every fix looks good for five minutes); state the success bar
  before reading the data.
