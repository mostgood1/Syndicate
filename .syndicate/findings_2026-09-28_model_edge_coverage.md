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

## RETRACTED: the "placeholder 0.500 fair" was NOT a defect `[corrected 2026-09-28, same session, before any code changed]`

**This section first claimed a second defect: that 24% of NFL rows priced against
a `market_fair_prob_over` of EXACTLY 0.500 -- "a placeholder, not a fair". THAT
WAS WRONG, and the user had already approved fixing it on the strength of the
claim.** It was withdrawn before a line changed, by recomputing the de-vig from
the book prices the same payload carries:

    row                             recomputed no-vig   served fair
    Deshaun Watson   Pass   187.5        0.5000            0.5
    Dontayvion Wicks Rec     41.5        0.5002            0.5
    Colston Loveland Rec     35.5        0.4992            0.5
    Makai Lemon      Rec     27.5        0.4987            0.5
    D'Andre Swift    Rec     10.5        0.4964            0.5

NFL prop markets are quoted near-symmetrically -- Watson is DraftKings -112/-112
and FanDuel -114/-114 -- so the de-vigged fair genuinely IS 0.500. It is correct
market data, and `_no_vig_over_probability` produced varied fairs on the other 38
of 50 rows, so the function works.

**WHAT MADE IT LOOK LIKE A PLACEHOLDER:** exactly-0.500 across twelve rows with
different players and lines reads as a sentinel, and the |edge| median on those
rows (48.44) is far worse than on the rest (21.92), which invited the reading
that the fair was fake. The causation runs the other way: `edge = model_prob -
fair`, so a 0.500 fair is simply where a confident-but-wrong model shows its
widest arithmetic gap. **The spread of the edge was evidence about the MODEL and
it was attributed to the MARKET.**

The inputs were two book prices sitting in the payload the whole time.

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
