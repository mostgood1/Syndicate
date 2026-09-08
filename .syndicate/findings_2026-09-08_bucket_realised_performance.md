# Which MLB live buckets actually make money: h2h is a clean null, spreads is a candidate, totals cannot be measured yet.

**2026-09-08, lane `profitable-buckets`, session 3492626c.**
`scripts/bucket_realised_performance.py`, `reports/bucket_realised_mlb.json`.
10 days of MLB live-gameline ledger, **94 games** with finals.

## The question, and why the existing number did not answer it

`bucket_live_edges.py` reports **paper** edge — how far the model's probability
sits from the market's. Its headline, `spreads q4_late` at 20.49pp and edge/se
6.35 over "n=2471", says the model disagrees with the book loudly and late. It
says nothing about whether the model is **right**, and nothing in this repo had
ever checked. That number was quoted repeatedly this session as though it meant
profit.

This scores the same ledger against real finals: the model prefers a side, did
that side win, at what rate against the rate the market implied for it.

## Result

| market | band | games | won% | market% | EDGE pp | sigma | holdout |
|---|---|---|---|---|---|---|---|
| h2h | q1_early | 95 | 43.16 | 46.58 | −3.42 | −0.67 | |
| h2h | q2_midearly | 94 | 51.06 | 48.23 | +2.83 | +0.55 | |
| h2h | q3_midlate | 94 | 54.26 | 49.24 | +5.01 | +0.98 | +0.77σ |
| h2h | q4_late | 94 | 63.83 | 64.29 | −0.46 | −0.09 | |
| spreads | q1_early | 94 | 54.26 | 50.12 | +4.14 | +0.81 | +0.28σ |
| **spreads** | **q2_midearly** | 94 | 64.89 | 52.64 | **+12.26** | **+2.49** | **+3.23σ** |
| spreads | q3_midlate | 94 | 60.64 | 51.46 | +9.18 | +1.82 | +1.84σ |
| **spreads** | **q4_late** | 93 | 67.74 | 53.53 | **+14.22** | **+2.93** | **+1.90σ** |
| totals | — | — | — | — | — | — | **REFUSED** |

**h2h is a clean null.** Every band inside noise. This is the market where the
model's probability is unambiguous — it is a home-win probability, no line
convention to get wrong — and it shows nothing.

**Spreads is a candidate, not a finding.** Three reasons to hold: it is the
**best of 8 buckets tested**, so the family-wise bar is ~2.7σ and only `q4_late`
clears it; the whole sample is **94 games over 10 days**; and the holdout is the
back half of those same games, not an independent period.

**Totals is REFUSED, which is a defect not a result.** The market's own de-vigged
probability miscalibrates by 10 points against my outcome resolution (predicts
49.0% overs, 58.9% landed). A book does not miss by ten points — that points at
the join, and it is recorded here for a separate lane rather than chased.

## The number moved 21σ → 2.9σ on the same data, and that is the finding under the finding

Three denominators, three answers:

| version | headline | sigma | why it was wrong |
|---|---|---|---|
| rows | +14.63pp | **+21** | 42,692 rows = **122 games**, median 334 rows each |
| per (game, line) | +14.24pp | +6.15 | ~5.8 lines per game, same final score |
| **per game** | +14.22pp | **+2.93** | one bet per game — the unit actually acted on |

Each correction came from an **internal inconsistency**, not outside validation:

1. **+21σ is impossible on its face.** Real betting edges are 1–3pp.
2. **The market miscalibrated by 10pp on totals** — and the gate that should
   have caught it was set at 10pp, so it passed by 0.001. Now 3pp.
3. **h2h and spreads disagreed when they should not.** h2h has one line per game
   and collapsed to 94/94 showing nothing; spreads had ~6 lines per game and
   kept showing +14pp. That asymmetry was the artifact announcing itself.

The first three answers were all wrong. Weight the fourth accordingly until it
survives a slate it has never seen.

## Next, in this lane and nothing else

1. **Is the spreads edge concentrated?** +14pp on 94 games is ~13 extra wins.
   A handful of blowouts would produce that. Per-game contribution is cheap to
   compute and is the difference between a signal and an anecdote.
2. **Extend past 10 days.** The ledger only goes back as far as it does; more
   days is the only thing that moves 2.9σ toward or away from real.
3. **Fix totals' outcome resolution** — recorded for another lane.
