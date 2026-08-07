# Handoff — board work, 2026-08-07 (continue from here)

Read this, then `plan_layer2_north_star.md`. Everything below is measured unless
marked otherwise.

---

## 1. ~~FIRST TASK~~ — **VERIFIED 2026-08-07 19:30Z on production. Nothing to do.**

Checked against a live pregame slate (15 MLB games, first pitch 22:40Z) — the
condition local data could not produce, because 2026-07-12 is all `final`.

**API** (`/api/board/book-grid?sport=mlb&date=2026-08-07&market=h2h&limit=60`):
every row carries `projection.side = "home"` with a signed
`edge_vs_market_pct`, and **both branches are exercised** — 12 positive edges
(mark home) and **48 negative** (mark away). The negative branch is the one that
had never been seen.

**Rendered DOM** (`/market-board/books`): 15 games × 3 markets × 2 side-rows.
**No row ever carries two markers** (`moreThanOne: 0`), and each (game, market)
has exactly one `◄` with a tooltip, e.g. *"the model favours this side (edge
+12.9 pts on home)"*. The paired side renders "the model does not favour this
side". `simSide` in `book_grid.html:258-274` trusts `proj.side` and flips via
`r.sides` on a negative edge — it does not re-derive the side, which was the
suspected failure mode.

*Method note, since two sessions have now been burned by this:* a first pass
counting `.bg-best` reported "44 rows with more than one marker". That class is
**reused** by best-price and projection cells; the marker is the `◄`/title pair.
A second pass grouped by game alone and reported "15 multi" — also wrong, because
a game spans three markets. **Neither was a board bug.** Group by
(game, market) and select on the title, not the class.

<details>
<summary>original task description</summary>

## 1. FIRST TASK — one unverified thing

**Check the sim-side Best highlight on production.** `cfefb1ed` makes the green
Best cell mark the side the model favours (positive edge → projected side,
negative edge → the opposite side). It is verified in code and by tests, but
**never seen against pregame data** — local data on 2026-07-12 is all `final`, so
edges are suppressed and no side gets marked.

```
https://syndicate-an21.onrender.com/market-board/books?sport=mlb&date=<today>
```
Look at the `h2h` tab pregame: exactly one side per row should be green with a
"◄" and a tooltip giving the edge. If both or neither are marked, the
`simSide` logic in `book_grid.html` is wrong.

---

</details>

## 2. State of the world

### Live on web (`syndicate`, srv-d88ahvrbc2fs73eodu30)
Deployed ~8 times today, all web-only. Current: `cfefb1ed`.

| | |
|---|---|
| `/market-board/books` | **L1-A book grid.** 11 books as columns, best/consensus/fair, per-market tabs, sortable, date + game state, projections, margin model |
| `/api/board/book-grid` | its serve-time API — `?sport=&date=&market=&limit=` |

### refresh-worker (srv-d91dpertqb8s73co8ls0) — **STILL ON `21efffae`, HELD**
Untouched since 14:31Z. Four commits are queued behind a deploy hold:

```
GATE   full MLB slate, OBSERVATION ONLY
WIN A  a39fe3d6  (#255)   -- SEE BELOW, its criterion changed and it may be droppable
WIN B  c256cc3e (#258+#257 removal)
       c8871b5a (#260)
       + re-enable EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN
```

**WIN A's original criterion is WRONG — do not use it.** It read "the hydrated
MLB rebuild interval must move ~90s → ~300s". Production already sits at ~296s
**without `#255`**, so that number cannot move and measuring it proves nothing.
See §6.5: `#251` works in steady state and fails only when a post-boot pass
exceeds 10s, which is a load condition.

Two options, and the second is preferred:
- **Drop WIN A**, fold `a39fe3d6` into a later window. Defensible — there is
  nothing to measure in steady state.
- **Keep it, measuring the right thing**: that the interval *stays* ~300s across
  a boot **under slate load**, where today it would decay. That needs the slate,
  so it belongs *after* the gate, not before.

Either way **`#255` is low priority now and must not hold up WIN B.** The
settlement autorun is the test that matters; `settled: 0` is the product
blocker.
The gate **never ran under load** — every reading was from an idle worker
(peak drifted 1540 → 1615 → 1789MB over the afternoon, bar was 1500MB, 0 kills
for 3h). The user accepted "assume we're back to pre-OOM state" and moved on.
That acceptance is recorded, not measured. `scripts/check_worker_memory_gate.py`
runs the whole check.

---

## 3. THE THREE GAPS the user named at close

### 3a. The Layer 2 board itself
Everything built today is **Layer 1**. The L2 surface (`/`, the consolidated
recommendation board) has not been touched. Its ranking still runs on
`_SCORE_SIM_WEIGHT = 0.5`, a stated prior nobody measured, and `settled: 0`
means it has never been validated against outcomes. **This is the biggest gap
and the plan's S6.**

What now exists that L2 should consume: `book_grid.py` (per-book prices, fresh
best), `prop_projections.py` (sim edge for props AND game lines),
`book_margin_model.py` (fair value for one-sided markets). L2 should read the
same `market_row` rather than growing its own copy — §3 of the plan.

### 3b. Odds freshness
**47% of production rows led with a stale best price.** S1b fixed the
*selection* (1,528 → 197 suspect, single-book unchanged at 733, so nothing was
hidden). What remains is §4e of the plan:

- **C1 cadence** — ~26 min between snapshots. Fine pregame, fiction live. S2.
- **C3 simultaneity** — cross-book claims are only true if the prices coexisted.
  Enforcing it took an apparent 716 arbs to ~3. Not yet enforced outside arb.

### 3c. Expanded markets
Only `us` region is requested (`SYNDICATE_LIVE_ODDS_REFRESH_REGIONS=us`, all
three services) → 11 books. **Decision already made and priced: take `eu` +
`us_ex` + `us2`.**

```
baseline (us)                     2.04M/mo   40.7% of the 5M cap
+ us2 everywhere                  4.07M
+ eu, us_ex on GAME LINES only    4.13M      82.6%  -- FITS
```
The load-bearing fact: **props are 98.5% of credit cost** because they bill
per-event, so a region on game lines only costs ~30K/month, not ~1M. `uk` is
declined — `betfair_ex_eu` is already in `eu`. Book lists are in §4d of the plan.

**Do S0 first**: MLB is only ~16% of spend and the other 84% is unattributed
(probably soccer). `by_market_family` telemetry is dead since 2026-08-01.

---

## 4. What shipped today

| ref | what |
|---|---|
| `#253` | **the OOM fix** — `mlb/cards.py` held ≤96 deepcopied page contexts; floor 3.1GB → 0.8GB |
| `#254` | ledger readers streamed (7 sites) |
| `#256` | settlement claims its run BEFORE the work — the crash loop |
| `#257` | memory diagnostics (added, then removed; `log_heap_census()` kept) |
| `#258` | null identity can no longer overwrite the wrong ledger record |
| `#259` | an absent market is not a compatible one |
| `#260` | `settled_rate_of_settleable` — 46% of the ledger can never settle |
| S1 | book grid + API |
| S1b | **fresh-only best/consensus** |
| S3 | sim projections — props *and* game lines, per segment |
| S4 | book-margin model for one-sided markets |

---

## 5. Operational facts worth not rediscovering

- **Deploy one thing at a time by pinned `commitId`**, never branch head:
  `POST /v1/services/{id}/deploys {"commitId": "<sha>"}`. Verify with
  `git merge-base --is-ancestor <later> <deployed>` → must be NO.
- **Web deploys are safe; refresh-worker is held.** `scratchpad/deployweb.py`
  pattern deploys web only.
- **The preview server does not auto-reload Python.** Two wrong-looking results
  today were stale processes, not bugs. Restart before believing a negative.
- **Local `data/` is a lossy mirror.** It produced a completely wrong finding
  today (see §6). Deploy and measure on production.
- Render logs cap at 1000 rows/window and **silently truncate**; boot boundaries
  must come from the events API, not log text.

---

## 6. Corrections made today — do not re-derive these

1. **"The sim over-projects starter length by +24 to +40 points."** WRONG. That
   came from the local mirror. Production: pitcher markets `median +1.8, mean
   +2.6` across n=90. Well calibrated.
2. **"#232's deploy at 02:53 delivered the shard."** WRONG — it was present at
   21:50Z, five hours before the first OOM.
3. **"canonical_market_key returns None for everything."** WRONG — the signature
   is `canonical_market_key(sport, *values)`; I passed the label as the sport.
4. **"The betting-card producer bug."** Already fixed — no malformed record
   written since 2026-07-22. The real problem was the denominator (`#260`).
5. **RESOLVED — `#251` is NOT a no-op, and `#255` is not what its commit says.**
   The loop interval defaults to **30s** (`intelligence_state.py:2018`), so a
   ~296s hydrated MLB rebuild interval is not natural cadence — `#251`'s 300s
   floor is rate-limiting, in steady state, today, with `#255` NOT deployed.

   Why the original `_prune_home_cache` analysis missed it: `#251`'s early
   return happens **before** the write, and the prune only runs **on** a write.
   When every sport short-circuits there are no writes, therefore no prunes,
   and the entries survive to 300s. `#251` is self-sustaining once established.

   **It fails only under load.** The first pass after a boot has an empty cache,
   so all 8 sports build and write, and each write prunes. Sport order is
   `mlb … soccer`. If that pass exceeds **10s**, MLB's entry is past its TTL
   before a later sport writes, gets pruned, and the cycle never establishes.
   During the crash loop MLB alone took **73 seconds** — so `#251` was genuinely
   defeated then, and the original measurement was right *for those conditions*
   and over-generalised to steady state.

   `#255` therefore removes an undocumented coupling between a serve-TTL and a
   rate limiter that fails exactly when the system is slow — i.e. when
   suppressing a 2.9GB rebuild matters most. **It is a robustness fix, not an
   activation fix.**

---

## 7. The rule that cost the most to learn

**Bound retention, not rate.** Six rate fixes failed that night; the one
retention fix worked — and two sessions had demoted it as "not urgent" six hours
earlier, because rates are what the code makes visible and nothing measured what
was still resident. `log_heap_census()` exists so that is measurable next time.

Corollaries, each paid for: a guard must sit where the memory is spent; a ceiling
that only skips does not bound cost; claim before you work; a log is ordered by
time, not causality; and **confirm the code ran before concluding the idea is
wrong.**
