# Handoff — board work, 2026-08-07 (continue from here)

Read this, then `plan_layer2_north_star.md`. Everything below is measured unless
marked otherwise.

---

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
WIN A  a39fe3d6  (#255)                          ALONE, 30+ min
WIN B  c256cc3e (#258+#257 removal)
       c8871b5a (#260)
       + re-enable EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN
```
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
5. **`#251` may not be the no-op `#255` claims.** Production shows the hydrated
   MLB rebuild interval already at ~296s (≈ `#251`'s 300s floor) **without
   `#255` deployed**. Either `#255` is unnecessary, or it fixes a different
   path, or the detector measures the wrong line. **Resolve before spending
   WIN A on it.**

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
