# PRE-REGISTRATION: Test B step 2 -- edge over Pinnacle, forward (2026-10-25)

Lane `live-cell-scorecard`, session d57baa09. **Written and committed BEFORE any forward order is graded.**
**The registration time is this file's commit time on origin/main.** Every order submitted at or after it counts;
nothing before it does.

**USER DECISION (relayed by the coordinator 332cb014, 2026-10-25):** "(a)+(b): register + fresher". That means:
pre-register edge over Pinnacle >= 0.4 pp with no freshness gate, NCAAF/NHL/MLB now, consensus as the control arm;
add NBA/NFL/soccer/WNBA once Pinnacle rows land; AND build fresher Pinnacle capture, with its credit cost brought to
the user before it ships.

The evidence it rests on is the retrospective in `.syndicate/findings_2026-10-24_live_cell_scorecard.md` s7 and s9.
Those cut points were chosen after seeing the data. This file exists so the forward test does not repeat that.

## Instrument (frozen)

**Script.** `scripts/pinnacle_edge_deciles.py` at the commit that adds this file. It is read-only.

**Population.** Settled, filled orders priced at a venue: live kalshi/polymarket, paper:<venue> and
paper:<venue>:ladder. Each needs an event_id, a two-way side and a market. Soccer h2h (3-way) is excluded. Only
orders with `submitted_at >= REG` count.

**Sports, by start date.**

- NCAAF, NHL, MLB: from REG.
- NBA, NFL, soccer, WNBA: from the first UTC day on which their `book_quotes` shard holds a Pinnacle row. Pinnacle
  capture for them is `bbc90e69`, loaded at the next full down/up. Until that day those sports are not in the Pinnacle
  arms (they stay in the control arm from REG).

**Edge.** De-vigged two-way fair at our line, as of `submitted_at`, minus (contract price + fee per contract), in
probability points.

**Outcome.** Flat ROI = mean(pnl_dollars / stake), net of fees.

**CI.** Game-clustered bootstrap, seeded (`live_cell_gate.flat_ci`).

## Arms (frozen)

| arm | rule | hypothesis | role |
|---|---|---|---|
| **P1 (primary)** | Pinnacle edge >= +0.4 pp | ROI > 0 | the candidate |
| P2 | Pinnacle edge < 0 | ROI < 0 | the filter candidate: "never buy above Pinnacle's fair" |
| C1 (control) | consensus edge >= +0.4 pp | no better than the population | Kaunitz-faithful (s9 note) |
| C2 (diff) | P1 orders minus C1-only orders | P1 > C1 | does Pinnacle add over the consensus |

## Decision bar (the scorecard bar, as decided 2026-10-24)

**P1 PASSES** when ALL of these hold:

- >= 150 settled bets, >= 40 games and >= 14 days since its sport's start;
- the game-clustered **CI95 lower bound on flat ROI > 0**;
- mean Pinnacle CLOSE edge > 0.

Passing is a recommendation to the user. Nothing reads it automatically. It would earn a live cell through the
per-cell gate's re-arm, not by bypassing it.

**P1 FUTILITY** at any weekly look once >= 150 bets: CI95 upper bound < 0, or mean close edge < -0.5 pp.

**P2 CONFIRMED** when, at >= 150 bets / 40 games, the CI95 upper bound < 0.

**Looks.** Weekly, in the Monday report, and nothing in between counts. Calendar stop: 2027-01-31.

## Freshness (part b) -- NOT a gate here; a secondary analysis only

**Correction to s7/s8 of the 10-24 findings.** The "Pinnacle age" there (median 68 min) is time since Pinnacle's
price last CHANGED. `odds_book_quotes` dedupes unchanged prices, so it is not how stale our copy was.

Our copy's staleness is the gap since our last fetch of that sport. Measured on 10-24 refresh runs, the median gap
between fetches is:

| fetch | median gap |
|---|---|
| NCAAF game lines | 2.5 min |
| NFL | 2.6 min |
| NBA | 3.5 min |
| NHL, MLB | 6.5 min |
| WNBA | 13.8 min |
| soccer pregame | 46 min |

The capture age per decision is NOT recoverable afterwards: the per-key `last_seen` sidecar keeps only the latest
value. So a freshness rule can be analysed only on orders placed after a fetch heartbeat exists. Once it does, P1
will be split by capture age (<= 2 min / > 2 min) as a secondary analysis. It is not a pass criterion.
