# The model_edge_pct gap, attributed: a plausibility ceiling and one unpriceable market — and a much larger question underneath

`[2026-10-14 23:26–23:36Z, session 4ab694ed, lane model-edge-gap-attribution, taking the lead filed on closing layer2-triad-recount]`

## The lead, and the guess inside it

Closing `layer2-triad-recount` hours earlier, I filed: *"`model_edge_pct` is
missing on ~21.6% of rows, concentrated in ncaaf (65.4%) and nfl (76.6%). Worth
attributing per sport: the board already prints `edge_unavailable_reason` inside
`projection`, so the reason is probably already being recorded and simply not
counted."*

**The guess was wrong.** Measured at 23:26:53Z over 846 gap rows: **94.0% (795)
carry no `edge_unavailable_reason` at all.** The lane's hypothesis is
**FALSIFIED**, and it was falsified in a structural way worth stating once —

> The **per-sport projection builders** record their refusals
> (`no no-vig fair: the market is not quoted on both sides`,
> `no probability to price: row has no line`, `prob_interval_swamps_edge`).
> `layer2_board._model_edge_for` — the function that actually decides whether a
> row gets a top-level `model_edge_pct` — records **nothing** on any of its
> `return None` paths. A reason field only upstream writes cannot explain a drop
> that happens downstream.

## What the gap actually is

Attributed by calling the **deployed** `_model_edge_for` branch logic and its
helpers over the served rows, `rows == total_rows` asserted per sport. Two reads,
ten minutes apart, as the slate grew (ncaaf 463 → 613 rows):

| branch | 23:30Z (n=805) | 23:36Z (n=809) |
|---|---|---|
| **CEILING:** `abs(edge) > 15.0` points, dropped not clamped | 431 (53.5%) | 464 (57.4%) |
| no probability at all: nothing to price | 319 (39.6%) | 291 (36.0%) |
| no market fair probability (model prob present) | 49 (6.1%) | 48 (5.9%) |
| no model probability (market fair present) | 3 (0.4%) | 3 (0.4%) |
| NOT AN OPPOSITE: projected `home` vs row side `draw` | 3 (0.4%) | 3 (0.4%) |

**100% of NFL's 229, 100% of NCAAF's 158 and 100% of MLB's 9 gap rows were the
CEILING.** So the concentration the lead flagged in exactly those two sports is
one guard firing, not a broken join. The rest resolves cleanly too:

- **the 291–319 "nothing to price"** are soccer `alternate_totals_corners`:
  `projected: 10.324` with `model_prob_over: null` **and**
  `market_fair_prob_over: null`. No probability exists, so no edge can.
- **the 48–49** are soccer rows that *do* carry the reason
  `prob_interval_swamps_edge` — the model probability is inside its own
  simulation noise. Working as designed, and logged.
- **the 3 NHL** are `spreads` where hockeysim prices only the home −1.5 puckline
  (the reason is recorded on 2 of 3).
- **the 3 soccer `draw` legs** carry an inner edge of 4.72 and are dropped by the
  two-way opposite check. `_model_edge_for`'s own comments say the three-way
  path should have handled these; 3 rows fall through. Small, real, named.

**Nothing here is a join fault.** That is the lead answered.

## The ceiling is doing most of the work, and it is not what it looks like

`_MODEL_EDGE_MAX_POINTS = 15.0`, justified at `layer2_board.py:1847-1871` on a
measured basis: MLB pregame **h2h**, 2026-08-08, where `fair 0.468 + edge 39.38`
implied ~86% on a game the market priced near even — *"the signature of a units
mismatch or a home/away join fault"*. The constant calls itself *"deliberately
generous — a genuine 15-point edge is enormous and still passes."*

Two measurements complicate that.

**1. The bar cuts the body of the distribution, not a separated population.**
Over all 1,951 rows carrying `projection.edge_vs_market_pct`:

| \|edge\| | 0–2 | 2–5 | 5–8 | 8–11 | 11–13 | **13–15** | **15–17** | 17–20 | 20–25 | 25–30 | 30–40 | 40+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rows | 297 | 450 | 327 | 240 | 113 | **93** | **75** | 102 | 91 | 92 | 54 | 17 |

93 immediately below the bar against 75 immediately above: **no trough at 15.0.**
431 of 1,951 (22.1%) sit above it. The bound was derived on MLB game h2h, where
legitimate probabilities live in 35–65%; it now fires overwhelmingly on NFL and
NCAAF **player props** (Receiving Yards, Rushing Yards, Receptions) and totals,
where that reasoning does not transfer. Max observed: 46.4 (NFL Receiving Yards).
Nothing above 50.

**2. It is a magnitude filter standing where a skill filter would go.** On NFL,
**228 of the 229 rows it rejected and 613 of the 670 it accepted carry the same
verdict**: `loses_to_market`. It separates large disagreements from small ones
*inside one model*, which is a different thing from separating models that work
from models that do not. Reading the ceiling as a quality gate would be wrong.

## The larger finding: whose model opinion is the ranking using?

The board already stamps `projection.model_skill.verdict` beside every edge, so
this needs no new instrument — only the right denominator. Over every row that
**does** contribute a model edge (n=3,143 at 23:36Z), graded on the verdict text:

| grade | rows | share |
|---|---|---|
| NEVER BACKTESTED (*"model never backtested — projection is unvalidated"*) | 1,175 | 37.4% |
| LOSES to the market/close | 1,109 | 35.3% |
| *"at the price: no established loss, ROI on model EV>0 −7.1% [−41.3%, +31.1%] over 210 bets"* | 745 | 23.7% |
| parity with the market | 79 | 2.5% |
| no verdict text | 34 | 1.1% |
| **beats the market** | **0** | **0.0%** |

**2,284 of 3,143 (72.7%) of the model edges feeding the ranking come from a model
whose own verdict says it loses to the market or was never backtested. Not one
row comes from a model the board says beats the market.** Per sport:

| sport | rows with an edge | LOSES | NEVER BACKTESTED |
|---|---|---|---|
| nba | 32 | 0 (0%) | 32 (**100%**) |
| nhl | 183 | 6 (3%) | 174 (**95%**) |
| ncaaf | 291 | 155 (53%) | 128 (44%) — **97% combined** |
| nfl | 820 | 613 (**75%**) | 150 (18%) |
| soccer | 1,555 | 181 (12%) | 641 (41%) |
| mlb | 130 | 66 (51%) | 38 (29%) |

**What this does and does not establish.** A model losing on average Brier can
still hold an exploitable edge on a subset — "loses to the market" is not "has no
signal anywhere". What it does establish is where the burden sits: using such a
model's edge as a ranking term requires naming that subset, and nothing in the
board does. 23.7% of rows sit under a genuinely honest verdict (an ROI interval
spanning zero is *"no established loss"*, not a win), and that is the best class
present.

**The suggestion layer is already better than the ranking layer, which is the
mitigation and is stated as one:** of the 17 rows carrying `suggested` in the
23:33Z read, **10 were `measured`** and 3 `loses_to_market`. n=17 is a count, not
a rate — but the gate is evidently reading skill where the ranking is not.

## Two instrument defects, found on the way

**A. `model_skill.verdict_class` is not a safe filter.** 308 rows carry a verdict
*text* reading "loses to …" under `verdict_class: measured` (305) or `parity` (3).
The vocabulary is **per-sport**: NCAAF writes `measured` — a *status* — where NFL
writes `loses_to_market` — a *verdict*. Worked example, verbatim from the board:

> `verdict_class: "measured"` / `verdict: "loses to the closing line by 2.86
> points of total MAE [+1.12, +4.59] over 100 games; 2.48x over-dispersed and
> 4.6 points high"`

The interval is entirely above zero: an *established* loss, under a class name
that only says someone measured it. Any consumer filtering
`verdict_class != 'loses_to_market'` admits all 308.

**B. The shortlist payload's withholding counters are GLOBAL, not per-sport.**
`rows_uninformative_ev`, `rows_admitted_by_blend`, `rows_below_value_floor` and
`opportunities_considered` came back **byte-identical across all eight sports**
on a `?sport=<s>` request (`opportunities_considered: 18241` for every one).
Attributing them to the sport you filtered on overstates it by the entire board.
The 2026-09-28 harness for this same question printed those counters per sport,
which is how a global number can be read as a per-sport one without anyone
noticing.

## What shipped

`scripts/audit_model_edge_gap.py` + `tests/test_audit_model_edge_gap.py` (20
tests, 7 mutants all caught), so this is repeatable rather than a scratchpad
reading. It calls the deployed `_model_edge_for` constants and helpers rather
than re-deriving the rule, refuses to report a share over a truncated page, and
re-checks defect **B** every run instead of trusting this reading.

Nothing was changed in `layer2_board.py` — it is claimed by five OPEN lanes
(`layer2-live-segment-actuals`, `layer2-suggested-opps`, `fair-price-v2`,
`signal-engine-nba`, `past-line-overlays`). The three code-side consequences are
filed as leads for whoever holds it.

## Method note

Two reads ten minutes apart, both with the row cap defeated and
`rows == total_rows` asserted per sport; where they differ the drift is the live
slate (ncaaf 463 → 613 rows) and both are shown rather than the friendlier one.
`ncaab` and `wnba` returned zero rows (out of season) and contribute to no share.
Every skill grade is read from a field the board already serves; none is inferred
from a model name or a sport.
