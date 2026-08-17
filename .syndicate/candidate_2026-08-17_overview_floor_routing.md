# Candidate — route the seven non-MLB sports to the expensive headroom floor

> Status: **CANDIDATE, NOT PREFLIGHT-PASSED. Read §4 before deciding — the
> measurement that was supposed to make this a clean win does not.**
> Lane: `refresh-worker-oom-recurrence`. Written 2026-08-17 ~01:0xZ.

## 1. The change

One routing decision in `_overview_headroom_floor_bytes`
(`syndicate/features/intelligence.py:2627`):

    if slug in _OVERVIEW_CHEAPLY_HYDRATED_SPORTS:
        return _OVERVIEW_MIN_SAFE_HEADROOM_STREAMED_BYTES, "streamed"   # 1500MB
    return _OVERVIEW_MIN_SAFE_HEADROOM_BYTES, "expensive"               # 3000MB

The seven in `_OVERVIEW_CHEAPLY_HYDRATED_SPORTS` (`:2622`) —
nba, wnba, nfl, ncaaf, ncaab, nhl, soccer — would stop taking the relaxed floor.
No new mechanism, no new constant, no new instrument. Testable offline.

## 2. Why it looked like the answer (M2, n=7)

Effective headroom (`max - unreclaimable`) at the start of every excursion
measured tonight:

    23:15:38  2231.0MB   +2078MB      00:08:26  2502.0MB   +2274MB
    23:30:06  2684.6MB   +2519MB      00:18:32  2952.7MB   +2860MB
    23:42:45  2636.0MB   +2331MB      00:31:46  2737.3MB   +2397MB
    23:54:45  2648.4MB   +2567MB

**All 7 below 3000. All 7 above 1500.** So at the check immediately preceding
each fatal sport, the expensive floor would have refused and the relaxed floor
waved it through. That is the whole mechanism of the guard's silence, and this
change addresses it directly.

It also closes the causal loop: those seven were routed to the relaxed floor on
a "+1.7MB for five sports" measurement taken with `_log_cards_context_memory`,
which exists **only for MLB** (`mlb/cards.py:182`). A sport with no instrument
read cheap, got the cheap floor, and is now measurably capable of +2.8GB.

## 3. What it would cost — and here is the problem

Distribution of effective headroom during ordinary operation, sampled
2026-08-17 00:36–00:47Z. **Only windows returning under the 100-row cap are
counted; the capped window's values are reported as presence, not as a count**
(`learnings.md:2917`):

    00:36:00-20   n=12  [COMPLETE]   headroom 3001-3010   >=3000: 12/12
    00:43:00-20   n=11  [COMPLETE]   headroom 3172-3186   >=3000: 11/11
    00:45:00-20   n=30  [COMPLETE]   headroom 2990-2996   >=3000:  0/30
    00:47:00-20   n=100 [CAPPED]     headroom 2913-2915   (values only)

**Routine operating headroom oscillates across 2913-3186MB. The proposed
threshold, 3000MB, sits in the middle of that band.**

Two consequences, both bad:

1. **It is a knife-edge.** Two of four admissible windows sat entirely below
   3000 and two entirely above, separated by ~200MB and a few minutes. Board
   coverage would flip between 8 sports and 1 on movements far smaller than the
   thing being guarded against.
2. **It cannot discriminate.** Fatal excursions START at 2231-2953MB. Routine
   operation RANGES 2913-3186MB. **Those overlap at 2913-2953MB.** No single
   value of this threshold separates "about to die" from "working normally",
   because at the moment of the check they are the same state. The floor is
   being asked to predict an allocation it cannot see coming — exactly the
   limitation `intelligence.py:2530-2542` already describes for the caller's
   breaker.

`intelligence.py:2595-2602` recorded the same behaviour from the other side:
with headroom at 2900.7 and 2587.3 the 3000 floor produced
`BOARD_OVERVIEW_READY sports=1` where every build in the preceding 3h read
`sports=8`.

## 4. Honest verdict on this candidate

**It would very likely stop the OOM kills, and it would do so by refusing a
large share of hydrated board builds.** That is not a bug in the change; it is
what the numbers say the trade is. It is a blunt instrument applied at the only
place a decision can currently be made.

I am therefore NOT recommending it as an unqualified fix. It is a legitimate
option whose cost is now quantified rather than guessed, and the choice between
it and the alternatives below is a product decision about board coverage, which
is the user's to make.

## 5. The alternatives, with what M1/M2 say about each

| option | catches the excursion? | coverage cost | buildable now? |
|---|---|---|---|
| **A. Route 7 to 3000MB floor** (this doc) | 7/7 by prediction | high, erratic — knife-edge in the operating band | yes, one line |
| **B. Watchdog abort** (`design_2026-08-17_watchdog_abort.md`) | acts on the ACTUAL excursion, not a predictor | low — only aborts when it is really happening | **not cheaply.** M1 measured **zero** stage markers across a 16s excursion, so the poll must go inside the hydration call tree |
| **C. Fix the allocation** | n/a | none | unknown — allocator still unattributed; retention hypothesis at `home.py:6766` untested |

**B is the better instrument and A is the available one.** B acts on the real
signal — the watchdog's 2s clock was the ONLY thing sampling during the
excursion (M1) — and so does not need to predict. Its cost is that M1 killed the
cheap implementation.

## 6. Preflight answers, so far as they can be given

- **Scope.** One function, `intelligence.py:2627`. Would be cut as a one-commit
  branch parented on refresh-worker's LIVE SHA — it runs off-main, and this
  session already recorded that deploying `main` carries 639 commits.
- **Expected effect.** Stated as a falsifiable pair, not a hope:
  `OVERVIEW_STOPPED_FOR_MEMORY` goes from **0** to non-zero within one board
  cycle (~90s), and `oomKilled` events go from ~5/hour to 0 over 2 hours.
  **And** `BOARD_OVERVIEW_READY sports=N` falls below 8 on some cycles — if it
  does not, the change did not engage and the kill reduction is someone else's.
- **Measurement.** `scripts/render_events.py --service refresh-worker
  --failures-only` for kills; `OVERVIEW_STOPPED_FOR_MEMORY` and
  `BOARD_OVERVIEW_READY sports=` for engagement and cost. Both must be read;
  reading only the first would record a board outage as a success.
- **Blast radius.** refresh-worker only. Persistent disk → stop-then-start, ~7
  min downtime, kills any in-flight sim. Inert on web (it does not run the
  intelligence loop, per `state.md`).
- **Rollback.** Revert the one-line routing, or redeploy the prior SHA.
- **Ledger.** No OPEN lane claims `intelligence.py` except this one.
  `learnings.md` "check guard thresholds against stage cost" is the governing
  rule and is what produced §3.

## 7. What must not happen

Do not ship this and read "kills stopped" as success without reading
`BOARD_OVERVIEW_READY sports=`. Given §3 the most likely outcome is that kills
stop **and** the board thins substantially, and a measurement that only looks at
the kill count would record that as a clean win. That is the failure mode
`learnings.md` "gate on the output, not the input" exists to prevent.
