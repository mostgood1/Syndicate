# The 15-point ceiling, tested against its own criterion: it refuses 470 rows that criterion would accept, and admits 26 it would refuse

`[2026-10-15 22:0x–22:3xZ, session 4ab694ed, lane model-edge-ceiling-implied-probability, on user instruction]`

## What was asked

`_MODEL_EDGE_MAX_POINTS = 15` drops `model_edge_pct` on 464 of 809 gap rows
(57.4%) — measured earlier tonight in
`findings_2026-10-14_model_edge_gap_attribution.md`. The open question was
whether a bound **derived on MLB game h2h** belongs on NFL/NCAAF **player
props** unchanged. This answers it with the distribution the bound's own
docstring says matters, not with an opinion.

The docstring (`layer2_board.py:1847-1871`) is explicit that the bound is not
about magnitude:

> So the bound is on PLAUSIBILITY IN PROBABILITY SPACE, not on magnitude for
> its own sake: an edge is accepted only if the probability it implies is one a
> bettor could act on.

So the test is: **of the rows it rejects, how many imply a probability a bettor
could not act on?**

## The measurement is not a reconstruction

I computed `implied = market_fair_prob_over + edge_vs_market_pct/100` — the
docstring's own arithmetic — and then checked it against the row's **own**
`model_prob_over`:

```
  agree within 0.005 : 2855
  disagree           :    0
  no model_prob_over :    0
```

**2,855 of 2,855, zero disagreements.** So the "implied probability" is not my
arithmetic at all; it is the model's stated probability read back off the row.
Every number below is the model's own claim about the world. Served board,
2026-10-15T22:0xZ, six sports, row cap defeated (`limit=5000`, `rows ==
total_rows` asserted per sport; no sport was excluded).

Thresholds are the docstring's: **impossible** = outside 0..1, **extreme** =
the 86-89%-against-a-near-even-market case it was installed to catch, taken as
>=85% or <=15%, **ordinary** = everything between.

## Result: the hypothesis is CONFIRMED, with one refinement that cuts the other way

| side | sport | class | n | ordinary | extreme | IMPOSSIBLE |
|---|---|---|---:|---:|---:|---:|
| REJECTED | mlb | game line | 2 | 2 (100%) | 0 | **0** |
| REJECTED | mlb | player prop | 9 | 9 (100%) | 0 | **0** |
| REJECTED | ncaaf | game line | 96 | 93 (97%) | 3 (3%) | **0** |
| REJECTED | ncaaf | player prop | 84 | 78 (93%) | 6 (7%) | **0** |
| REJECTED | nfl | game line | 28 | 24 (86%) | 4 (14%) | **0** |
| REJECTED | **nfl** | **player prop** | **236** | **194 (82%)** | **42 (18%)** | **0** |
| REJECTED | nhl | player prop | 61 | 61 (100%) | 0 | **0** |
| REJECTED | soccer | game line | 9 | 9 (100%) | 0 | **0** |
| | | **all rejected** | **525** | **470 (89.5%)** | **55 (10.5%)** | **0** |
| accepted | | **all accepted** | **2330** | **2304 (98.9%)** | **26 (1.1%)** | **0** |

Per-sport accepted control: mlb game line 87% ordinary (n=54), mlb prop 100%
(118), nba game line 100% (6), ncaaf game line 91% (175), ncaaf prop 100%
(135), nfl game line 99% (74), nfl prop 100% (614), nhl game line 100% (32),
nhl prop 100% (1000), soccer game line 99% (122).

**1. Not one rejected row implies an impossible probability.** 0 of 525. The
units/join error the bound was installed to catch does not occur in the
population it is currently refusing.

**2. 470 of the 525 rejected rows (89.5%) imply an ORDINARY probability** —
one a bettor could act on, which is the docstring's own acceptance test. Those
rows are refused by a bound whose stated criterion would admit them.

**3. The refinement, and it is real: the bound DOES enrich for extremes.**
10.5% of rejected rows are extreme against 1.1% of accepted — about **9x**. It
is a weak but genuine correlate of implausibility, concentrated in exactly the
market class the question was about: **NFL player props, 236 rejected rows,
18% extreme**, against 0% of the 614 accepted NFL props. So the bound is not
orthogonal to its criterion, and the hypothesis's "nothing like the 86-89%"
clause is too strong.

**4. But it also admits 26 extreme rows**, including 7 MLB game lines (13% of
that bucket) — the derivation market, failing the derivation criterion, and
passing.

**5. On MLB and NCAAF game lines the sign is INVERTED.** Rejected rows are
*more* ordinary than accepted ones: 100% vs 87% (mlb), 97% vs 91% (ncaaf).
Small n on the MLB side (2 rejected), but NCAAF's 96 rejected against 175
accepted is not small. A plausibility filter whose rejected population is more
plausible than its accepted population is not filtering on plausibility there.

**6. The derivation population is nearly absent.** MLB **h2h** specifically:
**3 rows** carry an edge on this slate, all accepted, all ordinary. Widening to
all MLB game lines gives 56. The bound is doing its work on NFL/NCAAF props
(320 of 525 rejections, 61%) — two market classes it was never derived on.

## What this means in one sentence

Judged by its own criterion the bound has an **8.5:1 false-positive ratio**: it
refuses 470 ordinary rows to catch 55 extreme ones, and lets 26 extreme ones
through anyway.

A direct test on the quantity the docstring names — reject when
`model_prob_over >= 0.85 or <= 0.15` — would, on this slate, refuse **81 rows,
all 81 extreme**, and refuse **zero** ordinary rows. That is strictly better by
the bound's own standard on both sides at once: it catches the 55 extremes the
ceiling catches, plus the 26 it misses, while returning 470 rows to the board.
The field it needs is already on every row and already validated against the
arithmetic above.

## What I did NOT do, and why it is the user's call

**No code change.** The bound gates `model_edge_pct`, which feeds ranking on
money-adjacent rows; 470 rows returning to the board is a ranking change, not
an observability one. Three things make it a judgement call rather than a
mechanical fix:

- **An ordinary implied probability is not a CORRECT one.** A -35.55-point edge
  on `nfl receptions` implying 14.85% is actionable as a probability and may
  still be a bad model. The ceiling may be absorbing model error it was not
  designed to absorb and nobody has costed that.
- **Skill is handled elsewhere, which is the argument for narrowing it.**
  `_apply_skill_reliability` already demotes measured losers (1,011
  established-loss rows) and `bucket_factor` already cancels the demotion for a
  validated pocket (794 rows). The plausibility guard is not the skill guard,
  and this repo's own rule is that a guard assuming HOW it fails is silent in
  the real failure.
- **Mechanism vs estimator** (`model_engine_standard.md`): returning 470 rows
  to the ranked population changes what the downstream rates were fitted
  against. Two mechanisms together have produced a negative interaction here
  before, in 4 of 4 markets.

So the recommendation is stated, not applied: **replace the magnitude proxy
with the criterion itself**, and if that is too large a step, apply it to game
lines first where the sign is inverted and the derivation population lives.

## Sample rejected rows, for the reader who wants to see one

```
  nfl    receptions        edge= -35.55  fair=0.5040  implied=0.1485
  mlb    strikeouts        edge= +22.28  fair=0.5990  implied=0.8218
  ncaaf  receiving yards   edge= -18.58  fair=0.5000  implied=0.3142
```

The third is the case in one line: a 31% probability, refused as implausible.

## Method notes

- Classification is by the row's own `model_prob_over` after the 2,855/2,855
  agreement check; the earlier pass used the reconstruction and reported 527
  rejected rows against 525 here — the two-row difference is rows carrying an
  edge and no `model_prob_over`, and the population is stated rather than
  reconciled away.
- `_MODEL_EDGE_MAX_POINTS` and `_as_float` were imported from the deployed
  module, not re-typed, so the ceiling under test is the one in production.
- Market class is `market in {h2h, h2h_3_way, spreads, totals, spreads_alt,
  totals_alt, moneyline, btts}` -> game line, else player prop.
- Script: `scratchpad/ceiling_implied.py` and `ceiling_by_sport.py`.

## ENGINE READ (added 2026-10-15 22:3xZ, owed by the standing rule)

The sections above are a BETTING read: the guard is miscalibrated against its
own criterion. That is only half of what this data says, and the half that
matters less. A >15-point disagreement with the market is far more likely a
MODEL DEFECT than a 15-point edge, so the 525 rejected rows are better read as
a **large-gap bug list** — and the ceiling has been suppressing the symptom
while leaving the cause in place.

Restricted to player props (461 of the 525; game lines excluded because the
engine question is per stat family):

| sport | family | rej | acc | rej% | over/under | mean abs edge | max |
|---|---|---:|---:|---:|---:|---:|---:|
| nfl | receiving yards | 108 | 261 | 29% | 45/63 | 27.9 | 49.9 |
| nfl | rushing yards | 79 | 122 | 39% | 25/54 | 24.9 | 53.1 |
| nfl | receptions | 46 | 145 | 24% | 20/26 | 24.5 | 48.1 |
| nhl | sog | 33 | 298 | 10% | 6/27 | 21.1 | 30.6 |
| ncaaf | receiving yards | 33 | 48 | 41% | 8/25 | 20.2 | 31.9 |
| nfl | rushing attempts | 25 | 38 | 40% | 2/23 | 24.2 | 34.8 |
| nfl | passing yards | 22 | 102 | 18% | 10/12 | 23.0 | 30.8 |
| ncaaf | rushing yards | 16 | 26 | 38% | **0/16** | 25.2 | 41.0 |
| nhl | assists | 14 | 268 | 5% | **0/14** | 18.1 | 21.4 |
| ncaaf | passing yards | 8 | 15 | 35% | **0/8** | **32.8** | 35.9 |
| mlb | strikeouts | **5** | **0** | **100%** | **5/0** | 26.4 | 43.4 |

(22 families have at least one rejected row; the full table is in
`scratchpad/ceiling_engine_read.py` output.)

**1. The gaps are CONCENTRATED, which is the defect signature.** Top 1 family
= 23% of rejected prop rows, top 3 = **51%**, top 5 = 65%. NFL
receiving/rushing/receptions alone is 233 of 461. Diffuse disagreement would
not pile up like that.

**2. The large-gap population is DIRECTIONALLY SHIFTED.** Among rejected prop
rows the model is over the market on **33.4%** (154/461); among accepted rows
it is over on **43.8%** (888/2028). The tail is skewed under, which is a bias
signature rather than a spread of independent disagreements.

**3. Six families are 100% one-sided, all under.** Scored against the
*measured* base rate p(over)=0.334 — **not** a 50/50 null, which would have
overstated this by two orders of magnitude:

```
  ncaaf rushing yards   0/16   P=1.50e-03
  nhl   assists         0/14   P=3.37e-03
  nhl   points          0/10   P=1.72e-02
  nfl   passing tds      0/9   P=2.58e-02
  ncaaf passing yards    0/8   P=3.87e-02
  nhl   saves            0/6   P=8.72e-02
```

No single family is decisive — the weakest is p=0.087. **Six at once, all in
the same direction, is the finding**, and it is stated that way rather than by
quoting the smallest number.

**4. `mlb strikeouts` is the cleanest single item: 5 of 5 rows rejected, 100%
of the family, all OVER, mean abs edge 26.4, max 43.4.** A family where every
row exceeds the plausibility ceiling in the same direction is a scale or
denominator bug, not an edge. `mlb walks_allowed` is 1 of 1 the same way.
These two are the only families the ceiling rejects outright, and they are
invisible on the board precisely because it does.

**5. What the ceiling costs the engine.** Dropping `model_edge_pct` on these
rows removes them from ranking, which also removes them from every
accuracy/CLV surface that reads the edge. So the families with the worst
projection error are the ones the evaluation layer can least see — the guard is
load-bearing for the blind spot. This is the same shape as the repo's own rule
that a guard assuming HOW it fails is silent in the real failure.

### Leads this opens (not taken here)

- **`mlb strikeouts` / `walks_allowed` scale check** — 100%-rejected families,
  one direction. Highest value per unit effort of anything in this table.
- **A one-sided-tail check as a standing engine instrument** — the 33.4% vs
  43.8% split and the six all-under families were free to compute from a board
  fetch, and nothing currently watches for them.
- **NCAAF passing yards carries the largest mean gap (32.8 points)** on only 8
  rows, which is a small enough population to inspect row by row.

None of these is a betting change; all three are projection-input questions.
