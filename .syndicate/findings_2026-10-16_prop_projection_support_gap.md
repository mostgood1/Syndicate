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

## STEP 2, run 2026-10-16 14:4xZ: the support I shipped does NOT settle the ceiling question, and the reason is that `sample_games` is a CALENDAR count

Publishing the support made step 2 possible for the first time. It came back
against my own hypothesis, which was that ceiling-rejected rows would be
low-support. Distinct (player, market, line, game) NFL prop markets, `kind ==
"prop"`, cap defeated: **157 rejected, 453 accepted.**

```
  median sample_games   rejected 5.0      accepted 5.0      <- IDENTICAL
  rows with <=5 games   156/157 (99%)     453/453 (100%)
```

**The rejected rows are not low-support. The entire NFL prop population is.**
It is week 6, so `sample_games` ~= 5 is simply "this season so far" -- a
**calendar count, not a volume count.** Braelon Allen has 5 team games and
almost no targets, and the field cannot tell him from a starter. So the field is
correct provenance and **insufficient as a gate**, which is worth stating
plainly given I shipped it expecting otherwise.

`projected_sd` is no better on its own (rejected median 10.8 vs accepted 20.8,
but that is confounded by magnitude -- a small projection carries a small sd;
the scale-free version, sd/mean, is 0.862 vs 0.757 with heavy overlap).

### What DOES separate them, cleanly

| discriminator | rejected | accepted | enrichment |
|---|---:|---:|---:|
| `projected/line` < 0.6 | **30 of 157 (19%)** | 4 of 453 (1%) | **19x** |
| yardage projection < 8 units | **23 of 101 (23%)** | 4 of 282 (1%) | **23x** |

IQRs tell the same story: `projected/line` runs 0.667..1.614 (median 0.818) for
rejected rows against 0.967..1.232 (median 1.078) for accepted.

**The separable signal is a low ABSOLUTE projection against a real line -- a
ROLE disagreement, not a sample-size problem.** Braelon Allen's issue is not 5
games; it is 3.8 projected yards against a 15.5 line. The model knows he has no
role and the market is pricing a player who does.

### But it only explains a fifth, which is the honest limit

19-23% is a strong enrichment and still a MINORITY. The other ~80% of
ceiling-rejected rows carry ordinary ratios and ordinary projections --
consistent with the prior finding that 89.5% of rejected rows imply an ORDINARY
probability. So the ceiling is discarding one part role-noise and four parts
ordinary disagreement.

### Where that leaves the recommendation

The sequenced plan survives with its middle step answered differently than
expected:

1. **DONE** for NFL -- support published and served (`5457b428`).
2. **ANSWERED, negatively** -- support does not separate rejected from
   accepted, because `sample_games` is a season-length count. **Sample size is
   not the gate.**
3. **So the ceiling should be replaced by TWO checks, not one:** its own stated
   criterion (an implied-probability bound, per
   `findings_2026-10-15_ceiling_implied_probability.md` -- which would refuse 81
   rows, all extreme, and 0 ordinary), plus a **low-absolute-projection / role
   check** for the ~20% that are genuinely implausible. A magnitude bound is a
   poor proxy for either.

Still a decision for the user, not a change I made: it moves money-adjacent
ranking on ~320 distinct markets.

### What would make support actually usable

A **volume** count rather than a calendar one -- targets, carries, or snaps
behind the rate, not games the team played. That is a producer change in
`nfl/props.py`'s rate computation, not a copy, and it is not claimed here.

## The opportunity field, verified against production payloads BEFORE the restart (18:5xZ)

Lane `nfl-prop-opportunity-volume`'s verification is not the served count --
`sample_games` passed a count check and still failed to gate. It is the field's
distribution on each side of the ceiling. That does **not** need the restart:
the served board supplies the ceiling classification (`edge_vs_market_pct`) and
the artifact supplies the companion volume row, which is exactly the join the
deployed code performs. One row per distinct (player, market, line, game).

```
  side           n      p10      p25   median      p75
  REJECTED      93     1.00     1.60     3.60     7.50
  accepted     298     1.80     3.20     5.00    16.40
  no companion volume row: 25 rejected, 35 accepted
```

| threshold | REJECTED | accepted | enrichment |
|---|---:|---:|---:|
| opportunities < 1.0 | 7.5% | 1.7% | **4.5x** |
| < 1.5 | 22.6% | 5.7% | **4.0x** |
| < 2.0 | 31.2% | 10.7% | 2.9x |
| < 3.0 | 40.9% | 18.8% | 2.2x |

**It separates, and `sample_games` did not** (5.0 vs 5.0). Every quantile is
lower on the rejected side. That is the lane's discrimination clause, met on
production payloads.

### But it is a SIGNAL, not a clean gate, and the overlap says so

Medians are 3.60 against 5.00 and the distributions overlap heavily. The most
selective threshold (<1.0) catches **7.5% of rejected rows**; the most
productive (<2.0) catches 31% but also flags **10.7% of accepted** ones. So it
cannot replace the ceiling by itself.

### The comparison I owe, because it cuts against this field

The earlier `projected/line < 0.6` discriminator was **sharper**: 19% of
rejected against 1% of accepted, a **19x** enrichment, versus 4.0x here.

**And the opportunity field is still the more valuable of the two**, for a
reason worth stating rather than assuming: `projected/line` is nearly the same
quantity the ceiling already gates on (a large negative edge *is* a projection
far below its line), so it is **derived** and can tell you almost nothing the
edge does not. `projected_opportunities` is **independent** -- it is volume, not
price disagreement. An independent signal at 4x is worth more to a gate than a
derived one at 19x, because only the independent one adds information. Stated
as reasoning, not as a measurement: nothing here tests their joint behaviour.

### What is still owed

- The **served** count (0 of 708 at 18:4xZ, worker unrestarted since 13:27:56Z).
  This preview joins the same two sources the deployed code joins, but it is a
  preview, not the served reading.
- **Coverage is partial:** 25 of 118 rejected rows (21%) and 35 of 333 accepted
  have no companion volume row at all, so a gate on this field is silent on a
  fifth of the population it would judge -- which is the `unknown must not
  default permissive` case, and the field is `None` there by design.
- Their joint behaviour (opportunities AND implied probability AND ratio) is
  untested. The ceiling recommendation still stands as two checks, and this
  measurement does not promote the opportunity field to being one of them.

## Joint behaviour of the candidate checks (19:0xZ) -- 72.4% of what the ceiling refuses has no plausibility OR role justification

I left "their joint behaviour is untested" in the section above, so this closes
it. Three classifiers over the same NFL yardage population, one row per
distinct (player, market, line, game), **442 markets**. No outcomes are
involved: this measures COMPLEMENTARITY, not accuracy.

```
  MAG   abs(edge_vs_market_pct) > 15      116 rows (26.2%)   production today
  IMPL  model_prob_over >= .85 or <= .15   21 rows ( 4.8%)   the docstring's own test
  OPP   projected_opportunities < 1.5      39 rows ( 8.8%)   the independent role signal
```

**Overlap with what production refuses today (MAG, n=116):**

| | rows | share of MAG |
|---|---:|---:|
| also IMPL | 21 | 18.1% |
| also OPP | 22 | 19.0% |
| IMPL or OPP | 32 | 27.6% |
| **NEITHER** | **84** | **72.4%** |

**The headline: 84 of 116 ceiling rejections (72.4%) are refused on MAGNITUDE
ALONE** -- neither implausible as a probability nor low-role. That is the same
conclusion the 89.5%-ordinary measurement reached, now reached through two
independent instruments on a different population slice.

### Two things I have to state against my own earlier claims

**1. `IMPL` is a COMPLETE SUBSET of `MAG` here -- all 21 of 21.** So on NFL
yardage the implied-probability criterion catches *nothing* the magnitude bound
misses. That does **not** contradict the earlier platform-wide finding (a
direct `model_prob_over` test would refuse 81 rows, 26 of which MAG accepts),
because that population was **all sports including game lines** and this one is
**NFL yardage only**. Different denominators; both true. I am flagging it
because quoting the 26 figure for this population would be wrong.

**2. My script printed "substantially overlapping, so one may suffice" and that
verdict is WRONG** -- it came from an arbitrary hard-coded threshold
(`both <= min*0.34`), not from the data. The actual numbers say the opposite:
IMPL=21, OPP=39, BOTH=11, union=49. Of 60 flag-instances only 11 are redundant
(18%), **OPP catches 28 rows IMPL misses and IMPL catches 10 that OPP misses**.
They are COMPLEMENTARY. The lesson is the obvious one: a heuristic verdict
printed beside real numbers gets read as a finding, so it should not have been
printed at all.

### What replacing MAG with (IMPL or OPP) would actually do

```
  refuses 49 rows (11.1%)  vs MAG's 116 (26.2%)
  MAG refuses, combined would ACCEPT:   84 rows returned to the board
  MAG accepts, combined would REFUSE:   17 rows newly caught
  opportunity UNKNOWN (gate silent):    58 of 442 (13.1%)
```

The 17 newly-caught rows are the whole argument for an independent signal: they
are invisible to a magnitude bound by construction. The 84 returned rows are
the cost side, and nothing here says they are PROFITABLE -- only that the
current bound refuses them without a stated reason.

### Still not established

- Whether the 84 returned rows win money. No outcomes were used anywhere in
  this arc.
- The 13.1% with unknown opportunity: a gate on OPP is silent there, by design
  (`None`, never permissive-by-default). Any real rule needs a stated behaviour
  for that slice, and this measurement does not choose one.
- Thresholds are unfitted. 1.5 opportunities and 0.85/0.15 are the docstring's
  and a round number; nothing here fits either.

## RESOLVED 2026-10-19: the `mlb strikeouts` lead in this file is WITHDRAWN

`[appended 2026-10-19 21:5xZ / 4:5x PM CDT, lane mlb-strikeouts-scale-check]`

The "Not established" section above left the `mlb strikeouts` 5-of-5 family standing as measured at 22:02Z and unverified since, because MLB was serving 0 rows. It has now been re-measured on a live slate and **it is not a scale or denominator defect**:

- `model_skill` carries `parity with the market: Brier +0.017 [-0.009, +0.042] over 193 starts; biased high ~13%` — the bias is MEASURED, with a sample size, published on the row.
- `market_shrink` (`mlb-market-shrink-2026-10-10`) pulls `model_probability_raw` 0.6652 to 0.4241 against a market fair of 0.4129 — **96% of the way to the price** — so `model_edge_pct_raw` **+25.65** is served as `model_edge_pct` **+1.539** (`ev_pct` 2.173).

**AND THIS FILE'S MEASUREMENTS USED THE WRONG FIELD.** Everything here that quotes an edge quotes `edge_vs_market_pct`, which is the RAW projection edge; the consumer reads `model_edge_pct`. For strikeouts those differ by **16.7x**. The conclusions survive for NFL / NCAAF / NHL / soccer only because their `calibration_method` is `identity`, so raw IS served — a coincidence this file never checked and did not know it was relying on.

Full resolution, including two further findings I drafted from this file's framing and had to withdraw as instrument failures: `.syndicate/findings_2026-10-19_mlb_strikeouts_scale_check.md`.
