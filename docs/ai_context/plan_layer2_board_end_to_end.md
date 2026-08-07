# The Layer 2 board, end to end: evaluation and one plan

Written 2026-08-07 after ten consecutive point-fixes (#235-#245) that each
corrected a real defect and none of which made the board trustworthy. The user's
verdict — "I feel like we are playing whack a mole" — is correct, and this
document exists to replace that mode with one plan.

Everything below is **measured on production**, not inferred. Where a number
appears, it came from the live API, the real 74MB quote shard, the Render logs,
or the served DOM.

---

## 1. What the pipeline is, and where it is actually broken

```
OddsAPI ──► live-odds-worker ──► web disk ──► refresh-worker ──► board state ──► web ──► UI
          capture             PUBLISH        PULL             enrich+gate      serve   render
             │                   │             │                   │             │        │
            §2.1               §2.2          §2.3                §2.4          §2.5     §2.6
                                                    │
                                              settlement/CLV  §2.7  ◄── the loop that is supposed to close
```

### 2.1 Capture — thin field, no anchor, and 76% of spend on the wrong lane

| measured | value |
|---|---|
| books captured | **11** (draftkings, betmgm, betrivers, williamhill_us, fanduel, fanatics, bovada, betonlineag, mybookieag, betus, lowvig) |
| sharp anchor | **none** — no Pinnacle, no Circa, no exchange |
| projected 30-day credits | **2,022,867** against a 5M cap |
| props share of spend | **310,240 / 410,127 = 76%** |
| game lines share | 21,988 = **5.4%** |
| MLB median two-sided hold | **6.25%** (p10 3.27, p90 7.36) |
| `batter_home_runs` | **12,409 rows, 100% one-sided** — no `under` from any of 11 books |

Two consequences. First, fair value is a median of eleven retail books rather
than an anchor — defensible, but it is the ceiling on every EV number we
publish. Second, we spend 76% of the budget on props and 5% on the game lines
where a sharp book would actually be available.

### 2.2 Publish — **CORRECTED: it works. The first version of this section was wrong.**

The original finding here read "publishing is failing right now — 100
PUBLISH_FAILED in an hour, not size-specific, small CSVs fail too". That was
wrong, and the way it was wrong is worth recording because it is the same error
class this document exists to eliminate.

What the fuller measurement shows:

| measured, 01:00–02:10Z | value |
|---|---|
| `PUBLISH_OK` | **1000** (hit the query limit) |
| `PUBLISH_FAILED` | 223 — *all* `HTTP Error 502` |
| failures by minute | **01:33 ×108, 01:54 ×95, 01:55 ×19**, 02:08 ×1 |
| web deploys finished | **01:34:06** and **01:55:10** |
| the 74MB MLB shard specifically | **127 OK / 9 failed (93%)**, publishing every 1–2 min |

The failure bursts are **web restarting for two deploys I triggered myself**.
The transport is healthy, including for the 74MB shard, and the sweep does not
advance its watermark on failure (`all_succeeded`), so deploy-window failures
retry and self-heal by design.

**The error:** a one-hour sample was taken, it happened to contain two of my own
deploys, and a systemic conclusion was drawn from deploy noise — without ever
checking the success rate or correlating against the deploy log. Measuring
failures without measuring successes is not a measurement.

What is genuinely imperfect here, and is *hardening* rather than an outage:
- `publish_hot_artifact` peaks around 250–300MB for one 74MB file (read_text,
  then `.encode()` again for the checksum, then `json.dumps`, then `.encode()`).
  Wasteful; currently survivable.
- `timeout_seconds=10` for an ~80MB JSON body is fragile — it succeeds today and
  is the kind of margin that disappears under load.
- The endpoint parses the whole body into memory on a 2GB instance.

None of these is causing the observed failures. They belong in a later hardening
pass, not ahead of the feedback loop.

### 2.3 Transport — three defects, all fixed this session, all the same shape

- #237 pull fired only when a file was **missing**, never when stale — the
  worker froze on a 21:03Z snapshot.
- #239 soccer shards by **fixture date**; the pull only asked for today, got a
  404 forever, and logged "absent" — which read as "no soccer quotes exist".
- #241 the pull lived **inside the cache it was supposed to invalidate**.
  Nothing changed because nothing was fetched; nothing was fetched because
  nothing had changed.

### 2.4 Enrich — de-vig now exists; identity is still the weak joint

- #238 shipped no-vig fair value. Before it, every EV on the board was
  `model_probability − vigged implied` — biased low by ~half the hold (~3.1
  points at our median).
- Identity is where props die. #236: WNBA carried `"Chelsea Gray OVER 1.5 3PM"`
  in **all four** identity fields; 0 of 27 rows priced against a shard holding
  2,615 prop quotes for 28 players.
- Simultaneity is not optional: requiring both legs fresh and within 180s of
  each other **dropped 88% of raw pairs** (2,354 → 282). Without it the shard's
  all-day log pairs a pregame price with an 8th-inning one.

### 2.5 Gate — now one rule, running at serve time (#245)

Current live verdict on 200 rows:

```
opportunity 14 · dead 20 · watchlist 166
reasons: no_market_posted 166 · live_market_stale 20 · fair_unavailable 9
```

### 2.6 Board — honest now, but thin

14 opportunities, zero blank Book/Age cells, **9 of 14 with no fair price**
(one-sided markets). Blended score exists; its weights are an unvalidated prior.

### 2.7 The feedback loop — **open, and this is the most important finding**

```
total_recommendation_records  8,276
settled                           0
matched                           0
unmatched                     8,276
   no_graded_rows             3,716   (outcomes never ingested)
   no_key_match               4,560   (outcomes exist, the join fails)
```

**8,276 recommendations, zero settled.** Graded rows that do exist are
`moneyline` only — no prop outcomes at all. So:

- no CLV, no ROI, no calibration;
- the blended-score weights **cannot be validated** — they are a prior forever;
- the sim edge, our entire differentiator, is **unfalsifiable**;
- and the `no_key_match` half (4,560) is the *same identity-join defect* as
  #236, just at the settlement end instead of the pricing end.

A system that produces recommendations and cannot learn whether they were any
good is not an OddsJam-class product. It is a very well-instrumented guess.

---

## 2.8 THE RUNTIME EXECUTION MODEL — the constraint the first draft ignored

The first version of this document traced the DATA FLOW and said nothing about
how the worker actually executes. That was the biggest hole in it, and it was
found the expensive way: by shipping a change that put refresh-worker into a
restart loop. `CLAUDE.md` names this as "the single most important
architectural constraint in the repo" and points at
`runtime_execution_model.md` and `worker_architecture.md`. Any plan that does
not budget for it is a plan for a different application.

### The worker is ONE serial process with a priority chain

`run_refresh_worker.py` dispatches autoruns through an `elif` chain. Exactly one
fires per cycle, in this order:

```
1 mlb_refresh   2 weekly_sports   3 soccer_weekly   4 reconciliation
5 evaluation_settlement    6 season_projections    7 preseason_projections
```

**Settlement is 5th of 7.** Any higher-priority autorun that is due preempts it
for that cycle. So "close the feedback loop" is not only a matching problem
(#247) — settlement is *structurally starvable*, and making it run more often by
shortening its interval does nothing if reconciliation keeps winning the chain.

The same process also hosts the intelligence-state background loop
(`start_intelligence_state_background_loop`), so board publication, artifact
pulls, the MLB sim tick and settlement all compete for one memory envelope.

### Memory is the binding constraint, not CPU

Measured on refresh-worker 2026-08-07, immediately before restarts:

```
ALL_PROCESS_MEMORY  accounted_rss_mb 2096   (real process RSS)
CONTAINER_MEMORY    memory_current_mb 3103 / 4096  (75.8%)
[refresh_worker] BOOTED  02:53:32 · 02:56:49 · 02:59:00 · 03:02:38
```

A ~3-minute restart loop. `build_intelligence_overview` has OOM-killed this
worker before (documented in its own source comment). Note the standing caveat
that `memory.current` includes page cache — but RSS alone was 2.1GB here, so
this was not only cache.

### What caused it, honestly

**My own #241 change.** The loop-level artifact refresh streamed a 74MB quote
shard plus ~40MB of odds_history **every 120 seconds**. Restart counts:

| window | boots | worker deploys |
|---|---|---|
| 18:00–20:00 (before) | 0 | 0 |
| 22:00–00:00 | 2 | 2 |
| 01:00–03:10 (after #241) | 6 | 2 |

Four unexplained restarts on a clean 3-minute cadence. Backing the interval off
to 600s (`SYNDICATE_ARTIFACT_REFRESH_INTERVAL_SECONDS`) stopped it.

### The rules this imposes on every phase below

1. **New periodic work on refresh-worker is never free.** It competes with the
   sim, the board build, and settlement inside a fixed 4GB envelope. Every phase
   must state its worker cost and its cadence.
2. **"Run it more often" is not a lever here.** It is the exact move that broke
   the worker. Freshness must be bought with smaller transfers or better
   invalidation, not higher frequency.
3. **Position in the autorun chain is a feature of the design, not an accident.**
   Anything that must run reliably cannot sit at position 5 behind four
   autoruns that can each preempt it.
4. **Every env change costs a deploy, and every deploy restarts the worker** —
   killing in-flight sims. Config is not free either.
5. **Serving is where freshness belongs when it is cheap.** #245's gate runs at
   serve time precisely because a pure function on web costs nothing and does
   not compete for the worker's memory. Prefer that shape.

---

## 3. The four structural defects behind eleven symptoms

Every fix #235-#245 traces to one of these. Fixing symptoms is why there were
eleven.

**D1 — Identity has no contract.** The same join (player + market + line +
event) is re-implemented at the producer, the enricher, the settlement matcher,
and each sport's cards module. It fails independently in each. #236, #221, and
settlement's 4,560 `no_key_match` are one defect wearing three hats.

**D2 — Freshness is not a first-class property.** Every stage assumes what it
reads is current. Nothing carries "as of when", so staleness is invisible until
it reaches a human — the user saw 7-hour-old odds before any instrument did.

**D4 — The worker's execution model is not budgeted for.** Work is added to a
single serial process with a priority chain and a hard memory ceiling as though
it were free. This is how a correct fix (#241) became an outage, and it is the
defect this document itself committed by planning without it.

**D3 — There is no closed loop.** Nothing measures whether output was correct,
so no parameter can ever be tuned by evidence, and every quality question is
settled by argument instead of data.

---

## 4. The plan

Five phases. Each has an exit criterion that is a **number**, not a judgement.
Nothing in a later phase starts before its predecessor's number is met.

### Phase 0a — Worker stability, and a cadence settlement cannot be starved out of
**Worker cost: reduces load; must be net-negative before anything else lands.**

The chain and the memory ceiling (§2.8) make this the true floor. Two pieces:

1. **Stop the restart loop.** Done for now by backing the artifact refresh off
   to 600s. That is a mitigation, not a fix — the real answer is to stop
   re-streaming a 74MB shard wholesale. Options, cheapest first: byte-range
   append reads (the shard is append-only JSONL, so only the tail is ever new),
   a per-sport split so MLB's 74MB does not move for a WNBA update, or a
   summarised quote index the board can read instead of the raw log.
2. **Take settlement out of position 5 of a 7-deep `elif` chain.** While it can
   be preempted by four other autoruns it will never be a dependable input to
   anything, no matter what its interval is set to.

**Exit:** zero unexplained `BOOTED` lines over 2 hours; container memory stays
under 70% across a full slate; settlement observed running on its configured
cadence rather than when the chain happens to let it.

### Phase 0b — Make the feedback loop RUN (revised)
The original Phase 0 was a publish-transport fix built on a wrong premise (see
§2.2). Transport is healthy; this is the real floor.

The settlement autorun last executed **15.3 hours ago**, and when it ran it
settled 0 of 8,276. Two separate problems, and the cadence one comes first
because nothing can be measured on a once-a-day grader:

1. **Cadence** — settlement rides inside `run_refresh_worker.py`'s cycle. It
   must run on a schedule tied to games finishing, not to whenever the worker
   happens to come round.
2. **Ingestion** — only `moneyline` graded rows exist. Prop outcomes are never
   ingested, which is 3,716 of the 8,276 unmatched.

**Exit:** settlement runs at least hourly; `graded_rows_available` non-zero for
props on a completed slate; `settled` > 0 for the first time.

### Phase 1 — One identity contract (kills D1)
A single `market_identity()` producing a canonical key from (sport, event,
market_key, player, line, side), used by **every** producer, the enricher, and
the settlement matcher. Not a shared helper anyone may bypass — the only
constructor, with producers emitting it and consumers refusing rows without it.

**Exit:** settlement `unmatched_no_key_match` drops from 4,560 to <100; prop
rows priced ≥90% wherever a shard covers the slate.

### Phase 2 — Close the loop (kills D3)
Ingest prop outcomes (only moneyline is graded today), settle the 8,276 pending
records, and publish CLV per signal bucket.

**Exit:** `settled > 0` and rising daily; CLV computed for ≥500 settled
recommendations; a per-bucket table (EV / sim-edge / steam / arb) with real
closing-line numbers.

### Phase 3 — Fair value everywhere (the blanks)
Two independent tracks:
- **Sharp anchor** for game lines: add `regions="us,eu"` (Pinnacle, key
  `pinnacle`) to the *game-line* fetch only — ~+5.4% credits on a 2.02M base.
  Then teach `consensus_fair_probability` to *prefer* sharp books, or we have
  paid for an anchor and used it as one vote of twelve.
- **Margin model** for one-sided props: de-vig a lone price using that book's
  own measured margin from its two-sided markets. Labelled
  `fair_method: "book_margin_model"` — never confusable with a true two-sided
  fair. This is the only thing that fills `batter_home_runs`.

**Exit:** `fair_unavailable` = 0 on the opportunity lane; every fair price
carries a `fair_method`.

### Phase 4 — The five signals, ranked by evidence (the north star)
Only now are the remaining signals worth surfacing, because only now can they be
scored honestly: arbitrage, middles, low-hold, mispricing, sim edge. Re-weight
the blended score from Phase 2's CLV instead of the current prior.

**Exit:** score weights derived from measured CLV, with the prior retired and
the derivation written down.

### Phase 5 — Layer 1 odds screen
Every book × every line per market. The data already ships — `quote.alternatives`
carries all 11 books on every priced row today.

---

## 5. Pregame vs live — they are different products

The board treats these as one lane with one set of rules. They are not.

| | pregame | live |
|---|---|---|
| price half-life | hours | **seconds to minutes** |
| stale = | normal (books post early and sit) | **dead** (#245: >900s on an in-progress game) |
| fair value from | full two-sided consensus | often one side only; markets suspend constantly |
| sim's role | full simulation from a known state | must re-project from *current* game state |
| capture cadence | a few times a day | must be continuous or the lane is fiction |
| what a stale row costs | a slightly wrong price | **a bet on a pitcher already pulled** |

The live lane is the harder product and the one where the sim edge is worth
most (books price live markets fast but shallow). It is also the one that
punishes every defect above immediately rather than eventually. **Recommendation:
make the pregame lane genuinely excellent through Phase 4 first, and treat live
as a Phase 5 product** — not because it matters less, but because a live board
built on an open feedback loop and a failing publish path will be confidently
wrong in real time.

---

## 6. Invariants — the actual anti-whack-a-mole measure

Rules that make the failure classes impossible rather than fixed:

1. **One gate.** `opportunity_gate.evaluate` is the only thing that decides
   eligibility, it is pure, and it runs at serve time. No consumer re-derives a
   lane — that duplication (a Python rule and a JavaScript copy) was the defect
   in #244.
2. **One identity.** Phase 1. A row without a canonical key is rejected at the
   producer, not repaired downstream by each consumer's own guesswork.
3. **Every number carries its provenance.** `fair_method`, `edge_priced_against`,
   `board_score_components`, gate `reasons`. A number a reader cannot take apart
   is one they must simply trust, and this session produced three that were
   wrong while looking authoritative (0 hold, +135% EV, 8.5-hour-old "live"
   prices).
4. **Absent must never render as a value.** `Number(null)` is `0` and `0` is
   finite; that alone put a fake "0 at 0.0% hold" on the board (#242).
5. **Freshness is judged on the BOOK clock**, never our capture clock.
6. **No measurement, no weight.** Any ranking constant must cite the CLV that
   set it, or be labelled a prior in the code.
7. **Measure failures against successes, and against your own deploys.** §2.2
   of this document was originally wrong because it counted 100 failures
   without ever counting the 1000 successes beside them, or noticing that both
   failure bursts landed on my own web restarts. A rate is a measurement; a
   count is an anecdote.

---

## 7. Order of work

```
Phase 0a worker stability + cadence ← the actual floor (§2.8); everything else
                                     competes with it for one 4GB envelope
Phase 0b make settlement RUN       (publish was a false alarm, §2.2)
Phase 1  identity contract        ← kills the largest defect class
Phase 2  close the feedback loop  ← makes every later decision evidence-based
Phase 3  fair value everywhere    ← sharp anchor + margin model
Phase 4  five signals, CLV-weighted
Phase 5  Layer 1 screen, then the live lane as a product
```

Phases 0-2 are unglamorous and are the whole difference between a board that
looks like OddsJam and one that is worth betting from.
