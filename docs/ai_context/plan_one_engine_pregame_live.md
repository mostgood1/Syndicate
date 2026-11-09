# One engine, pregame and live: the plan `[ADOPTED 2026-11-09 — D9–D12, user: "Yes, adopt and start"; lane syndicate-decision-engine, umbrella #736]`

**What the user asked for, verbatim (2026-11-09):**

- "i feel like we are still WAY BEHIND my expectations of a single AI engine that makes use of all our advanced stats,
  sim engine data, and betting data"
- "we need the decision engine to be thinking about pregame and then also be able to assess live decisions using all
  the same data but based on game shape/stat progress at a certain point in the game and projected outcomes"

This plan is a new phase, **1B**, for `plan_syndicate_decision_engine.md`. That plan designed the layer this needs (§3 L2,
signal experts and a skill registry) but never put it on the roadmap. It also handed in-play to a separate program (E7),
which is the opposite of one engine. Nothing here changes live capital: D6 (canary until a pre-registered gate passes)
stands.

---

## 1. Where we are (surveys of origin/main, 2026-11-09; ledger readings marked VERIFIED)

**Pregame.**
- `decision_record.py` writes one record per line on every board build, **in shadow**. Nothing reads it for the
  board, placement or size (`decision_record.py:8-10`).
- It prices every line at the market consensus. The sim's weight is `DEFAULT_MODEL_WEIGHT = 0.0` (`:56`). The sim
  earns weight only when the daily optimizer's w* has a lower bound above 0 (`:727-755`); none does.
  - The `#727` refit on 11-01 found 0 of 122 cells with β > 0 (VERIFIED).
  - The `#704` forward read on 11-02 put the sim's weight on 10,695 orders at −0.10 [−0.38, +0.05] (VERIFIED).
- The Phase 2 paper track (11-09 read, VERIFIED) has no look yet:
  - P1 −0.39% CLV, n 96 / 74 games;
  - P2 −1.85%, n 284 / 199;
  - the Suggested comparator −7.30%.
- **No source produces a per-line Δ with its own σ** (L2's contract). The prop under-tilt is computed per line and read
  by nothing. Referee, weather, rest and travel are collected or computed and applied to no line. Venue flow is not
  stored.

**The learning pieces overlap and contradict each other.**
- **Three multipliers on one row** each lower a line's rank: the static market-skill table, the bucket factor and the
  optimizer factor. Their floors multiply to 0.25 (`portfolio_commit.py:337`).
  - The static table has 46 hand-written entries, last measured 09-14, with no refit loop.
  - The shipped bucket JSON is empty.
  - The optimizer covered 25 of 219 cells on 10-24; 167 were "insufficient" (VERIFIED).
- **The optimizer's stake shrink is computed and discarded**: the market-staked basis overwrites it
  (`portfolio_commit.py:800-806`).
- **Three separate fits of the same quantity**, the sim's weight against the market: the optimizer (outcome, per cell),
  the `#727` harness (manual, per cell) and the `#704` pooled read. All say about zero or negative.
- **Mismatched machinery:**
  - a linear blend in `decision_record` against a logit blend in the staked profile;
  - two meanings of "phase": pregame/live in the optimizer, season phase in the profile and the tuner.

**Live.**
- **Producers:**
  - Live re-sims or lenses run for NBA (on since 10-13), NCAAB and WNCAAB (on), NCAAF (on), NHL (refused every game on
    11-09, fix `7d48129c5`, reading owed), MLB (offseason) and soccer (lens on; its re-sim trigger is off).
  - The NFL flag's fleet value is unverified, and WNBA is off until its 2027 opener.
  - Cadences run 60–180 s, against a Kalshi re-price of about 11 s.
  - Outputs: margin, total and segment histograms. Per-player remaining-stat histograms exist for NBA, MLB, WNBA and
    soccer. NHL, NFL, NCAAF and soccer **compute period logs and discard them** (`#767(c)`).
- **Two live decision paths, and neither is the engine:**
  - The board → `portfolio_commit` path reads the re-sim's `model_edge_pct` through `live_gameline_join`. Its gates:
    - quote age (600 s);
    - the `#762` lane-age gate, default on (VERIFIED: 0 of 5,630 priced records past the ceiling);
    - the college quote-behind-score refusal;
    - college segment pricing, off (`#763`).
  - **In-play entries** (`inplay_entries_live.py` / `_paper.py`) price on the **book median** (`FAIR_VERSION =
    inplay_book_median_novig/1`) and read **no re-sim**. Exits compare the bid against the **entry-time** probability
    (`execution_exits.py:883`), not a live re-fit.
  - DecisionRecord blocks in-play by construction (`decision_record.py:833-834`). In-play writes its own schema,
    `inplay_decision_record/1` (VERIFIED writing since 11-01).
- **Measured live skill (VERIFIED, lane `in-game-trading`, `#715`, `#765`):**
  - Kalshi leads the books in play (correlation +0.44). A book-consensus in-play edge marks out at −1.26c after the
    fee, over 1,613 side-samples on 11 games.
  - NBA re-sim vs the `pregame_rate` bar: no significant difference at any cell (132 games).
  - **NCAAB re-sim beats the bar** on h1 at the tip, on h2, and on the full total from minute 20 (282 paired games).
    **The only positive live lead we have.**
  - NHL score/time baseline: NO-GO (21 games).
  - The MLB live model's Brier was 0.287 against the market's 0.247 (3 games).
  - Real in-game Kalshi fills, 10-23..11-09: asks 0.40–0.55 −10.7% on n 369; asks ≥ 0.55 about +30% on n 32 (a small
    sample, and the basis of the 0.55 floor loaded 11-09).

**The honest reading.** The pieces exist: sims, live re-sims, stat progress, advanced inputs, odds history, venue
quotes and graders. What is missing is the **one place** where they meet a line at an instant, each earns or loses
weight automatically, and every decision (pregame and live, board and order) reads the answer. Building that place
does not by itself create edge. It turns "which data helps, where, and when in the game" from hand-run studies into
something the engine learns every night. The measurements so far say most sources will start at about 0 weight on
liquid main lines.

---

## 2. The design: one engine, evaluated at any instant

```
            state s_t                      evidence E_t (as-of t)                    belief                         decision
  pregame:  t < start                market prior: sharp fair / consensus /    p(line | s_t, E_t) =         EV_lb at the executable
  live:     period, clock, score,     live venue mid                           sigmoid( logit p_prior(t)       venue price, net of fee,
            possession, fouls,       experts, each a Δlogit with σ:              + Σ_i w_i(cell) · Δ_i(t) )   minus latency and
            pitcher, lineups on       pregame sim · live re-sim (state-          σ² = σ_prior² + Σ w_i²σ_i²    adverse selection (live)
            floor, stat progress      conditioned) · stat progress · game        cell = sport × family ×       → take / rest / wait /
            per player                shape · availability · refs · weather ·    segment × phase ×             hold / exit
                                      rest · steam · venue flow                  clock bucket × season phase
                                                     │
                                  one DecisionRecord per (line, instant) — pregame AND live — in shadow first
                                                     │
                     one learner, nightly: per-expert, per-cell weights, hierarchical partial pooling,
                     applied only when the lower bound is above 0; engine read → sim owners
```

**One state.**
- Pregame is `t < start`.
- Live is the game state at `t`: period, clock, score and possession, plus the sport's state variables (fouls and
  bonus, pitcher and pitch count, power play, red cards), lineups on the floor, and **stat progress** per player.
- The live lenses already assemble most of this. The engine reads the state; it does not rebuild it.

**One prior: the market at `t`.**
- Pregame: the sharp fair (Phase 1's Syndicate Fair), else the weighted consensus.
- Live: the live market. Kalshi's mid leads the books in play (VERIFIED), so in play the venue's own two-sided mid is
  the prior wherever an identity check holds, else the live book consensus.
- "Market is the prior" (principle P1) holds in both phases. Every other source must beat it.

**Experts.** Each one proposes a shift on the log-odds scale (Δlogit) with its own σ, per line, at `t`.

| Expert | Pregame Δ | Live Δ | Exists today |
|---|---|---|---|
| Sim | pregame sim vs prior | — | per line (`model_probability_cal`) |
| Live re-sim | — | state-conditioned projection vs live prior | NBA, NCAAB/WNCAAB, NCAAF, NHL (fix pending), MLB; soccer lens |
| Stat progress | — | a player's pace vs projection (minutes, usage, attempts) → that player's props | remaining-stat histograms for NBA, MLB, WNBA, soccer |
| Game shape | — | process vs result: shooting luck, pace, xG vs goals, foul trouble → totals, margins, segments | partly inside the re-sims; not separate |
| Segment | ladder of segment projections (h1/h2/q/p) | the same, from the live histograms | basketball `game_chip_intervals`; NHL/NFL/NCAAF/soccer discard theirs |
| Prop under-tilt | +1.0..+2.4pp | — | per line, read by nothing |
| Availability | status vs priced-in | in-game injury or ejection | in the sim inputs only |
| Referee crew, weather, rest/travel | small Δs | refs (fouls, pace) | collected; no Δ |
| Steam / sharp move | sharp-book move direction | live line move | single-book term off since 10-02 |
| Venue flow | Kalshi taker imbalance | the same, live | not stored |

**One record.**
- DecisionRecord v2 carries `phase`, the state snapshot `s_t`, the prior with its basis and age, and an
  `experts[]` list (each Δ, σ and weight with its source).
- **Pregame:** one record per line per build, as today.
- **Live:** one record per live line per tick, in append-only `decision_records/<date>.live.jsonl`. It supersedes
  `inplay_decision_record/1` and keeps that schema's fields.

**One learner.**
- It replaces, in order once it passes its gate:
  - the optimizer's w* in the record;
  - the three rank multipliers;
  - the static market-skill table;
  - the `#727` harness.
- **Cells:** sport → market family → market → segment → phase (pregame / live) → **clock bucket** (live only, by
  share of the game elapsed: 0–25 / 25–50 / 50–75 / 75–95%) → season phase, with partial pooling up that tree.
- **Fast truth:**
  - pregame: CLV against the sharp close (the consensus close where none exists, stated as the softer standard);
  - live: the fee-net **mark-out** against the venue mid at +300 s.
- **Slow truth:** the outcome, for both.
- **A weight is applied only when its lower bound is above 0.** It is shrunk toward 0, nothing is switched off, and
  every line stays its own decision.
- **Engine read, nightly per sport:** bias, calibration slope, and the biggest disagreements the market won, pregame
  and live **by clock bucket**. That queue goes to the sim owners: the user's "secret sauce" loop, now including the
  live re-sims.

**One policy.**
- The same EV_lb at the executable price.
- Live adds three terms that the measurements say are real:
  - a **latency** penalty for state and quote age (our cadence is 60–180 s; Kalshi re-prices in about 11 s);
  - the **adverse-selection** term from fills (in-play maker fills measured −16.6c/contract);
  - the existing state gates (lane age, quote-behind-score).
- Exits read the **current** `p_decision`, not the entry-time probability.

**One surface.**
- Every line, pregame and live, shows the prior, each expert's Δ with its earned weight, the final p, and the EV at the
  venue.
- The board, Suggested, cheat sheets, the portfolio, in-play entries and exits all read the record.

---

## 3. Build sequence: shadow first, every step gated

Each step is its own lane under this umbrella, with the files claimed by path and a falsifier written before any data
is read. **No step changes a stake, an order or the board until its gate passes and the user decides.**

| Step | What | Gate (pre-registered before its data) |
|---|---|---|
| **M0. Contract + live evidence log** | Record v2 schema; a live evidence log, per live line per tick, with state, every re-sim output, quotes and as-of stamps. Today's live re-sim files are overwritten each tick, so no live learner can train on them. | Replay one live night from the log and reconstruct every live line's evidence at any `t`: 0 mismatches. |
| **M1. Experts emit Δ+σ** | Pregame: sim, under-tilt, rest, refs, weather, steam. Live: re-sim, stat progress (NBA, MLB, WNBA, soccer first), segments. Keep the NHL/NFL/NCAAF/soccer period logs; fix the NHL name join (`todo:34`). | `off != on` reachability per expert; a coverage table per sport, phase and clock bucket. |
| **M2. The learner, in shadow** | A nightly hierarchical fit; weights written into the record; the engine read published. It runs beside the three multipliers and replaces nothing yet. | Held-out log loss of `p_decision` against the prior alone, per sport family, pregame and live separately, CI below 0. Also reported: the number of cells with a lower bound above 0. |
| **M3. One policy on paper, pregame and live** | Phase 2's paper track reads `p_decision`, and a **live paper book** reads it at the executable live price. The live book replaces the book-median in-play paper fair. | Live: fee-net mark-out at +300 s above 0 at ≥ 400 bets / ≥ 100 games (game-clustered), then outcome ROI. Pregame: Phase 2's edge gate, unchanged. |
| **M4. Surfaces and retirement** | Everything reads the record. The three multipliers, the static table, the optimizer's record weight and the separate in-play fair are retired. | Only after M2 and M3 pass. Canary live, per D2/D6. |

**Order and rough timing.**
- M0 and M1 can start now and overlap. M2 needs about 3–4 weeks of logged evidence, so live logging must start first.
- None of this waits for Phase 2's gate, and none of it touches Phase 2's registered test (its rules are frozen).

---

## 4. Where it can plausibly pay, ranked by evidence

1. **NCAAB / WNCAAB live totals and second halves.**
   - The only positive live lead: the re-sim beats the pregame-rate bar on 282 games.
   - College has no Pinnacle at all, so the market prior is softer.
   - `#763` keeps college segment pricing off until this kind of gate passes.
2. **Live props from stat progress.**
   - A player's pace against his projection is information a slow venue may not price.
   - Unmeasured. The NBA join exists but has no scored prop edge.
3. **College pregame where no sharp book exists.** The consensus close is the softer standard: the NCAAB test drafted
   11-09 (paused) becomes D12 below.
4. **Thin markets** (WNBA, segments, props).
5. **Main lines pregame in NFL / NBA / soccer:** expect weights about 0. That is a measured expectation, not a
   failure of the engine.

**Will not be chased again** (already measured as priced in or negative):
- raw sim probabilities on main lines;
- book-consensus in-play edges;
- take-profit exits;
- the derived-market surface (E3);
- news timing (E5).

---

## 5. Ownership: what this plan asks of each lane

| File / area | Owner today | Asked for |
|---|---|---|
| `decision_record.py` (`#709`) | lane `decision-record-shadow` | the v2 schema and the live record (M0) |
| `inplay_entries_*.py`, `execution_exits.py` | lane `in-game-trading` (E7) | the live paper book reads `p_decision` (M3); exits read the current p (M4). Every existing guard stays. |
| live re-sims per sport | the sport lanes (`nba-live-*`, `ncaab-live-*`, `wncaab-module`, NHL, NFL) | emit outputs to the live log; keep period logs; fix the NHL join |
| `daily_optimizer.py`, the skill tables, `portfolio_commit.py` sizing | model-scorecard, `sim-stake-*` | read the learner's output in shadow; retire only at M4 |
| the learner (new), the live evidence log (new) | a new lane under this umbrella | M0–M2 |

---

## 6. Risks, stated before the data

- **Integration is not edge.** M2 may find almost no cell with a lower bound above 0. That is a result, recorded as
  one, and it says where the sims need work (the engine read).
- **Latency.** At a 60–180 s cadence, a live expert can be right and still lose to an 11 s venue. The latency term and
  the mark-out truth exist to measure exactly that.
- **Live data volume.** A record per live line per tick is large. The log is compressed and retained per the
  evidence-store rules, and its size is measured in M0.
- **Shared files.** `portfolio_commit.py` and `decision_record.py` carry loan chains. Every change goes through its
  owner lane or a recorded loan.

---

## 7. Decisions — ADOPTED 2026-11-09 (user, verbatim: "Yes, adopt and start", answering "Adopt the one-engine plan (D9–D12) and start M0, the live evidence log?")

| # | Decision | Recommendation |
|---|---|---|
| **D9** | Adopt "one engine, pregame and live" as Phase 1B, run in parallel with Phases 1–2, shadow only | Yes |
| **D10** | Live goes through the same record, learner and policy. The in-play program (E7) becomes this engine's live half, not a separate path. Its live entries switch to `p_decision` only after M3's gate. | Yes |
| **D11** | Truth for live decisions: the fee-net mark-out at +300 s (fast) and the outcome (slow). Pregame: the sharp close, else the consensus close. | Yes |
| **D12** | Fold the paused NCAAB consensus-close test into M2/M3, as the gate for markets with no sharp close | Yes |

**First step (started 2026-11-09):** open the M0 lane and start the live evidence log, because every later step trains on it.
