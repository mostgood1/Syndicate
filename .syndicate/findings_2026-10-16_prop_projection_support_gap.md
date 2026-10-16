# The ceiling exists because the support field doesn't: 0 of 705 NFL and 0 of 391 soccer prop projections carry a sample count, and 91% of ceiling-rejected prop rows carry none

`[2026-10-16 03:5x-04:3xZ (2026-10-15 22:5x-23:3x CDT), session 4ab694ed, follow-on from findings_2026-10-15_ceiling_implied_probability.md]`

## Why this was the next action

The ceiling study's engine read flagged `mlb strikeouts` (5 of 5 rows rejected,
all one direction) as the highest-value item. **It could not be re-measured:**
by 03:54Z MLB and NBA served **0 rows** each and NHL served 2, because their
10-15 games had finished and the board drops finished games. That is the
repo's own rule that a finished slate reads as a regression, not a defect.

So the target moved to NFL/NCAAF, which still served 1,507 rows, and the
question became the one the `mlb strikeouts` row would have answered anyway:
**is a ceiling-rejected projection a disagreement or a defect?**

## Two corrections to numbers already in `state_model.md` [model-edge-ceiling]

**1. The row counts are inflated 1.47x as a count of distinct markets.**
`edge_vs_market_pct` is the OVER-direction edge regardless of the row's side
(verified: `model_prob_over 0.681 - market_fair_prob_over 0.5174 = 0.1636` ->
`edge_vs_market_pct 16.36`, exactly). So when the board surfaces both sides of
one market, the same disagreement is counted **twice in the same direction**.
Measured: **387 rejected NFL+NCAAF rows -> 263 distinct (player, market, line,
game)**, with **124 markets surfacing both sides**. The ratio claims (89.5%
ordinary, 8.5:1, 33.4% vs 43.8%) are unaffected because the inflation scales
both sides; the row COUNTS are not. "470 ordinary rows refused" is about **320
distinct markets**.

**2. "The tail is skewed under" was the wrong frame, and the control says so.**
My ratio read conditioned on `abs(edge) > 15`, which SELECTS ratios far from
1.0 — so a 0.707 median among rejected rows meant nothing on its own. With the
accepted population as control, one row per distinct market, props only:

| sport | family | n rej | median rej | n acc | median acc |
|---|---|---:|---:|---:|---:|
| nfl | receiving yards | 49 | 0.765 | 171 | **1.159** |
| nfl | rushing yards | 39 | 0.707 | 79 | **1.125** |
| nfl | receptions | 27 | 1.143 | 86 | 1.067 |
| nfl | passing yards | 11 | 0.894 | 57 | 1.021 |
| nfl | rushing attempts | 10 | 0.756 | 23 | 1.077 |
| ncaaf | receiving yards | 4 | 0.923 | 8 | 1.343 |

**All 495 accepted prop rows pooled: median `projected/line` = 1.0785 (+7.85%),
and only 148 of 495 (29.9%) project BELOW the line.** The model's central
tendency is **above** the market. The ceiling-rejected tail sits at 0.71-0.77,
the **opposite** direction.

So this is not a calibration offset extending into the tail. It is **bimodal**:
a model that normally sits ~8% above the line, and in a few hundred markets
sits 25-30% below it. That is a stronger defect signal than a uniform bias,
and it is the corrected reading.

## The actual defect: there is nothing to gate on but magnitude

Every collapsed projection carried `sample_games=None`. That turned out to be
the whole story. Prop rows carrying a `projected` value, by whether ANY support
field is set:

```
  sport     rows   support fields present
  nfl        705   NONE
  ncaaf       69   sample_games=69, projected_sd=44
  soccer     391   NONE
```

- `sample_games`: populated on **69 of 1,165** prop rows (**5.9%**)
- `projected_sd`: **44 of 1,165** (**3.8%**)
- `samples`, `n_games`, `support`, `games`, `sample_size`: **0** each
- Among the **206** ceiling-rejected prop rows, only 18 carry `sample_games`
  and 11 carry `projected_sd` — **188 of 206 (91.3%) carry no support at all**

**NCAAF populates it on 69 of 69 rows. NFL and soccer populate it on 0 of
1,096.** The capability exists in one module and not the others, which is the
platform's standing convergence gap rather than a new bug.

This is precisely the failure `model_engine_standard.md` was written for: a
field the consumer could read, unfed, and **indistinguishable from a working
feature at every level except the data**. With no support field, a magnitude
ceiling is the ONLY instrument available — so the crude guard is not an
oversight, it is the consequence of the missing input.

### What that costs, concretely

The collapsed rows (projection under half the line, while the accepted
population sits 7.85% above it) are rotational players, and nothing on the row
says so:

```
  Braelon Allen    receiving yards  line=15.5  proj=3.800  ratio=0.245  edge=-49.93
  Jalen Brooks     receiving yards  line=21.5  proj=5.333  ratio=0.248  edge=-48.73
  Colby Parkinson  receiving yards  line=15.5  proj=4.800  ratio=0.310  edge=-46.27
  Bo Melton        receiving yards  line=16.5  proj=6.000  ratio=0.364  edge=-43.70
```

19 such rows across ~5 players. A 49-point "edge" on a receiver with almost no
season volume is small-sample noise wearing an edge's clothes, and **no field
on the row can tell the two apart.**

Two rows are worse because they are **ACCEPTED and live**:

```
  Jayden Daniels  interceptions  line=0.5  proj=0.000  edge=+5.40
  C.J. Stroud     interceptions  line=0.5  proj=0.000  edge=-1.48
```

A projection of **exactly 0.000 interceptions** for a starting QB is not
credible, and because the resulting edge is small it passes the ceiling
untouched. The guard catches implausible EDGES; it cannot catch an implausible
PROJECTION that happens to imply a small edge. That is the same shape as this
repo's rule that a guard assuming HOW it fails is silent in the real failure.

## Hypotheses I tested and must record as FALSIFIED

**1. Sack yardage leaking into QB rushing yards — EXONERATED by code.**
`player_stats.py:500` accrues `rushing_yards` only when
`play["rusher_player_id"] == pid`, and a sack has no rusher, so sack yardage
cannot enter. I had this as the leading explanation for negative QB rushing
projections; it is wrong.

**2. `projected = -0.400` is a shared constant — NOT ESTABLISHED.** It looked
like one because two different QBs (Jordan Love, Kirk Cousins) carried exactly
-0.400 on an earlier fetch. On re-measure only Kirk Cousins did (2 rows), and
`-0.4` appears nowhere else platform-wide. At one decimal of resolution, -2
yards over 5 games gives -0.4 honestly. **A negative observed average is
legitimate for a pocket QB**, so this is not a unit bug and I am withdrawing
the claim. What remains notable is only that a structurally degenerate market
(a 1.5-yard line for a QB who never runs) yields a -21 to -40 point "edge".

**3. My own "ncaaf rushing yards / passing yards did not replicate" — WRONG.**
They are still **0% over** (0/16 then 0/2; 0/8 then 0/2). They dropped off the
one-sided list only because my script requires n>=6. **My filter hid a
replication**, and the direction held in every family that still had rows.

Also stated plainly: the second fetch's NFL rows are largely a **subset** of
the first's (same slate, finished games dropped), so agreement between them is
attrition-stability, **not** independent replication. A real replication needs
a different slate date.

## Recommendation (a decision, not a change I made)

**Populate `sample_games` and `projected_sd` on NFL and soccer prop
projections, then gate on SUPPORT before magnitude.** NCAAF already does it on
69 of 69 rows, so this is convergence onto an existing pattern rather than new
design. With support present, the ceiling can be narrowed to what its docstring
actually claims (an implied-probability check, per the prior findings file)
instead of standing in for a support check it was never meant to be.

Sequenced, because `model_engine_standard.md` requires a reachability test
before correctness tests and warns that adding a mechanism to a calibrated
engine requires re-fitting what was absorbing it:

1. Populate the support fields (observability only, no scoring change).
2. Measure how many ceiling-rejected rows are low-support vs genuine.
3. Only then decide whether the magnitude ceiling narrows or goes.

Step 2 is the measurement that currently cannot be taken at all, and it is the
one that would settle the ceiling question outright.

## Not established

- Whether the collapsed rows are **unprofitable**. They are implausible as
  projections; nothing here tests their ROI.
- Why NFL and soccer do not populate the support fields (not traced — the
  reason could be as small as a field the builder never copies).
- The `mlb strikeouts` 5-of-5 family stands as measured at 22:02Z and is
  **unverified since**, because MLB has served 0 rows since its slate finished.

## Method

Served board, `limit=5000` with `rows == total_rows` asserted per sport, any
truncated sport excluded. `_MODEL_EDGE_MAX_POINTS` and `_as_float` imported
from the deployed module. Field names were **discovered** from the payload, not
guessed — my first ratio script assumed `projection_value`/`point` and returned
0 rows for every family, which is what prompted the key census that found
`projected` and the row-level `line`. Scripts: `scratchpad/dup_and_ratio.py`,
`ratio_control.py`, `find_bad_projections.py`, `rushyd_shape.py`,
`support_field.py`.
