# The NFL model-edge coverage gap is the GUARD WORKING, not a plumbing break

`[measured 2026-09-28 ~16:2xZ on the served payload, lane layer2-triad-alignment,
session 4ab694ed]`

## The question

Why does `model_edge_pct` reach so few served Layer 2 rows, and is the scoring
model actually being applied to each opportunity?

## The answer in one line

**The scorer runs on 100% of rows. On NFL it has nothing to say, because NFL's
projections disagree with the market by a median of ~22-31 probability points and
a 15-point sanity guard correctly rejects them.** Raising the guard would push
demonstrably broken numbers onto the board.

## Measured, same payload so pool and served are the same instant

    sport   rows_with_model_edge / scored      served with model_edge
    nfl              91 / 682   = 13.3%              6 / 200  =  3.0%
    ncaaf           505 / 1000  = 50.5%            110 / 200  = 55.0%
    soccer          195 / 763   = 25.6%              1 /  20  =  5.0%

By kind, and this is the sharp end — **same engine (smartsim2 runs both football
sports), opposite outcome**:

    sport   kind   rows   projection   model_edge   sim_component != 0
    nfl     game     83      5   6%       0   0%          0   0%
    nfl     prop    117     45  38%       6   5%          6   5%
    ncaaf   game    200    200 100%     127  64%        127  64%

`sim_component != 0` tracks `model_edge` EXACTLY in every sport (0/0, 127/127,
6/6, 1/1). So **`model_edge` is the model's only route into the score.** Where it
is absent the row is ranked on market EV alone and the model contributes
literally zero — while `score` and `score_v2` are present on 200/200 rows, which
is why "is the scoring model applied" reads as yes from the field list alone.

## Why NFL's edges are rejected

`_MODEL_EDGE_MAX_POINTS = 15.0` (`layer2_board.py:1861`), a sanity bound on a
probability-space edge.

    sport   rows w/ edge_vs_market_pct   |edge| median   above cap   signed median
    nfl                44                    31.41         86%          +21.21
    ncaaf             200                    11.04         36%           -3.54

Excluding rows priced against a placeholder fair (below), NFL is STILL 21.92
median against NCAAF's 10.90 — roughly **2x more divergent on the same engine**,
and systematically POSITIVE rather than centred.

Worst NFL rows, verbatim from the served payload:

    prop Rushing Yards   over 55.5  Quinshon Judkins  model=0.0002 fair=0.5101 edge=-50.99
    prop Receiving Yards under 35.5 Denzel Boston     model=0.9916 fair=0.5    edge=+49.16
    prop Passing Yards   over 187.5 Deshaun Watson    model=0.9844 fair=0.5    edge=+48.44

A model asserting 0.02% and 98.4% on ordinary prop lines is not carrying a
suppressed edge; it is wrong. The guard is the only thing standing between those
numbers and the board's ranking.

## A SECOND, independent defect found on the way

**24% of NFL rows (12 of 50, all props) price against `market_fair_prob_over`
of EXACTLY 0.500** — a placeholder, not a market fair, across different players
and different lines. Their |edge| median is 48.44 against 21.92 for real-fair
rows. An "edge" against a placeholder is just the model's distance from a coin
flip wearing the name of a market disagreement. NCAAF has 15 such rows (7.5%),
all game rows.

**And 39 of 44 NFL rows carry `model_skill.sample_games = 0`** — unmeasured. Only
5 carry `measured_market_skill` (15 games).

## What was NEARLY reported and was wrong

NFL game-row `projection` coverage read as **6%**, against a ledger subject
`[nfl-board-projection-coverage]` claiming 100% on 2026-09-04. That is NOT a
regression. Split by commence date:

    2026-09-29 (tonight's PHI @ CHI)     5 rows    5 with projection  100%
    2026-09-28 (finished)               34 rows    4                  11.8%
    2026-10-02 .. 10-06 (future weeks)  87 rows    0                   0%

The board mixes three slate dates; future weeks have no projections yet, which is
correct. Coverage for the LIVE slate is 100%. This is `learnings.md`'s standing
rule in a new costume: split board coverage by game state, or a finished/future
slate reads as a regression. The ledger's own metric (`unmatched_game_rows` on
`/api/board/book-grid`) no longer exists in that payload, so the 2026-09-04
number could not be reproduced like-for-like and is NOT claimed as broken.

## What this blocks

The user's third question — compare the PREGAME scoring model against a LIVE one
— cannot be answered on NFL while 86% of its model edges are suppressed before
the scorer sees them. The comparison would be measuring the guard, not the
models.

## What NOT to do

**Do not raise `_MODEL_EDGE_MAX_POINTS`.** Its docstring already records the
failure it was built for, and the rows above are exactly that failure. The work
is in NFL's projection calibration, which the ledger independently reports as
losing to a frozen baseline with ratings whose implied uncertainty is the same
order as their own dispersion.
