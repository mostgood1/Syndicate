# Plan — pregame vs live cadence (S2)

Written 2026-08-08. Grounds `plan_layer2_north_star.md` §S2 in measured numbers
rather than targets, because the obvious reading of that stage — "make pregame
5 minutes and live 60 seconds" — is **unaffordable by a factor of two**, and
nothing in the plan says so.

**This is a plan, not shipped work.** Every number below is measured; every
design choice is argued; none of it is implemented.

---

## 1. Where we actually are

Measured on production 2026-08-08 16:45Z, MLB, quote age at the selected best
price, 596 sides across h2h/spreads/totals:

| state | n | p50 | p90 | max |
|---|---|---|---|---|
| pregame | 596 | **17.8 min** | **258 min** | **624 min** |
| live | — | not measurable, no live games at this hour |

Against §S2's exit (`pregame under 5 min`, `live under 60s`): pregame **misses
by 3.6×** at the median. The p90 is the more alarming number — **4.3 hours** —
and it says the problem is not a slow uniform cadence but a long tail of rows
that are barely refreshed at all.

Two things this does NOT mean, both of which I asserted earlier today and had to
withdraw:

- It is not "every row is 9 hours stale". That was a pre-slate snapshot.
- It is not an S1b failure. S1b (fresh-best selection) is **done and passing**:
  `rows_with_suspect_best` is 1,794/15,123 (11.9%, from 47%), and every
  remaining suspect row is also `all_quotes_stale` — i.e. suspect-best now
  survives only where nothing fresh existed. Relative staleness is solved.
  **Absolute age is not, and that is this document.**

---

## 2. The constraint that shapes everything: the budget

From S0 (measured, `GET /api/ops/oddsapi/quota`):

```
burn            62,076 credits/day  ->  1.86M/month  =  37.2% of the 5M cap
by family       props 59.8%   segment 23.8%   alternate 11.9%   full_game 4.4%
per-event billed families total 95.5%
MLB is 92.8% of all spend
```

**Naive uniform 5-minute pregame is 3.6× current burn = ~134% of cap.** It
cannot ship. Any plan that does not confront this is not a plan.

The asymmetry that makes a tiered design work:

| family | share of credits | cost of going 17.8m -> 60s |
|---|---|---|
| full_game (game lines) | **4.4%** (~2,731/day) | ~17.8× -> ~48.6k/day |
| props | **59.8%** (~37,121/day) | ~17.8× -> ~660k/day — **impossible** |

Game lines are cheap because they bill per *sport*; props bill per *event*. So
**game lines can go fast and props cannot**, and that is not a preference, it is
arithmetic.

---

## 3. Proposed tiers

Four tiers, keyed on **game state × market kind**. State is already on the row
(`game.state`, populated for MLB; see §6 for the gap).

| tier | scope | target age | est. credits/day |
|---|---|---|---|
| **T1 live game lines** | `state=live`, full_game | **60s** | ~48.6k |
| **T2 live props** | `state=live`, props, **unsuspended only** | **2–5 min** | ~25k (see below) |
| **T3 pregame game lines** | `state=pregame`, full_game, T-6h onward | **5 min** | ~5k |
| **T4 pregame props** | `state=pregame`, props | **30–60 min** | ~37k (≈ today) |

Estimated total ≈ **116k/day = 69% of the 5M cap**, against 37.2% today. That is
a real increase and it must be a decision, not a side effect.

**Why T2 is bounded by "unsuspended only".** A live prop on a suspended market
is un-bettable, and books suspend constantly during play. Polling suspended
markets is the single largest avoidable cost in the live tier. This needs the
suspension flag to be read, not assumed — if we cannot detect suspension, T2
must not ship at 2–5 min.

**Why T4 barely moves.** Pregame props are 60% of spend and the least
time-sensitive thing on the board: a player prop posted at 10am is usually still
live at 6pm. Spending the budget here to chase a 5-minute target would consume
everything T1 needs.

---

## 4. Triggers, which matter more than intervals

A fixed interval is the wrong primitive for the live tier. Three state changes
should force a refresh regardless of when the last one ran:

1. **Game state transition** (pregame -> live, live -> final). The final
   transition is what stops us pricing a settled market — `opportunity_gate`
   already has the rule; it needs fresh state to apply it.
2. **Lineup posting** — already wired for MLB sims (`MLB_LINEUP_STATE`), not
   yet used to trigger an odds refresh. The market moves hard on a scratch.
3. **Steam / large consensus move**, which the odds-history layer can already
   detect (`STEAM_DETECTED`).

Triggers are cheap because they fire rarely. Intervals are expensive because
they fire always. **Prefer a trigger to a shorter interval wherever the event is
detectable.**

---

## 5. Where each tier runs

The north-star plan says "live capture goes on live-odds-worker". That was
written before 2026-08-08 and needs revisiting, not obeying:

- live-odds-worker is **2Gi** and spent last night OOM-crash-looping. Root cause
  was the MLB live-lens Monte Carlo (+1,445MB), now moved to refresh-worker —
  after which live-odds-worker's peak RSS went 1,740MB -> 158MB.
- So it now has real headroom, and it is the correct home for T1/T2. But its
  headroom is *newly* won and unproven across a full slate.
- refresh-worker (4Gi) now owns the live-lens loop *and* the sim tick *and* the
  L2 board build. It is not a dumping ground.

**Recommendation:** T1/T2 on live-odds-worker as the plan says, but **only after
one full slate of clean memory** on the post-move build. Do not stack live
capture onto a box whose stability is 12 hours old.

---

## 6. What has to be true before this can ship

Ordered by whether it blocks.

1. **`game.state` must be populated outside MLB.** Measured 2026-08-07: it is
   `None` for every NFL, WNBA and soccer row. Tiering keys on state, so for
   three of four active sports **every tier would resolve to the same bucket**.
   This is the hard blocker.
2. **Suspension detection for T2.** Without it, live props cannot be polled at
   2–5 min within budget.
3. **A credit measurement per tier, not per sport.** S0 gave us `by_market_family`;
   this needs `by_tier` or the 69%-of-cap estimate stays an estimate.
4. **NFL week self-pinning** (§S2 names it). Root-caused 2026-08-07:
   `_NFLDataProvider.games()` is week-keyed and discards the requested date;
   `preseason_target_week` returns `min(unplayed weeks)` and nothing refreshes
   the status column, so it pins to 1 forever. Forward scope for NFL is
   meaningless until fixed. **Not fixed.**

---

## 7. Exit criteria

Stated before building, per §6 of the north-star plan:

- **T1**: live game-line p50 age **< 60s**, p90 **< 180s**, measured during a
  live slate — not inferred from an idle hour.
- **T3**: pregame game-line p50 **< 5 min**, p90 **< 15 min**.
- **T2/T4**: no target on age. The criterion is **cost**: total daily burn stays
  **under 70% of cap** with the tiering live, measured over a full week, not a
  day.
- **Anti-cheat**: `rows_single_book` must not rise. Faster polling that drops
  books is a regression wearing an improvement's clothes — the same guard S1b
  used.

---

## 8. What this plan deliberately does not do

- **Does not chase 5-minute pregame props.** 60% of spend, least
  time-sensitive, and it would consume the live budget.
- **Does not add a new worker.** Three services is already the constraint that
  produced last night's incident.
- **Does not assume the board gets better.** Faster quotes make the board
  *fresher*, not *right*. The board still ranks on `1/overround - 1` and cannot
  pick a side until S6 lands. Cadence and correctness are independent, and
  shipping this will not make the board recommendable.
