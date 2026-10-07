# Soccer "model edge scale": not a units bug -- the sim spreads each team's goals too thinly across its squad -- 2026-10-06

Lane `soccer-model-edge-scale` (session 5942cf5f). User: "look into the soccer model edge scale issue". The issue came from
`findings_2026-10-06_published_negative_ev.md`: published soccer rows' model EV `(fair + me/100) x odds - 1` was -54% (n=2,215, 10-05).
All numbers are read-only from the local fleet, 2026-10-06 ~21:30-22:30Z.

## H1 (units) -- FALSIFIED

Soccer `model_edge_pct` is in absolute probability points like every other sport. On served rows,
`me = (model_prob_over - fair) x 100` exactly:

- SOT over Kaua Prates: model 0.3221, fair 0.1956 -> +12.65
- first scorer Japhet Sery: model 0.0016, fair 0.0452 -> -4.36

On 10-05 recorded rows, every soccer `me` sits inside the board's +/-15 cap (`layer2_board._MODEL_EDGE_MAX_POINTS`, :1868). Under
the absolute reading none implies p <= 0 or p >= 1. Path: one-sided props -> `_model_edge_for` -> `_modelled_fair_edge_for`
(`edge_vs_modelled_fair_pct` against a `book_margin_model` fair); 1X2 -> `_three_way_leg_edge`.

## H2 (the model's probability is wrong) -- CONFIRMED; the cause is ALLOCATION

Recorded 10-05 soccer rows, median fair -> median `me` -> implied model probability:

| market | n | fair | me | implied model |
|---|---|---|---|---|
| first goal scorer | 1,563 | 0.053 | -4.03 | ~0.013 |
| anytime scorer | 1,298 | 0.114 | -7.34 | ~0.041 |
| last goal scorer | 1,258 | 0.044 | -3.18 | ~0.012 |
| shots on target | 807 | 0.223 | -8.49 | ~0.138 |
| totals / h2h | 202 / 69 | 0.50 / 0.35 | ~0 / +4.3 | ~market |

`poisson_scorer_race` (`soccer_scorer_markets.scorer_race`) is sound arithmetic over its input, `anytime_scorer_probability` from the
sim's `player_props` (last scorer equals first by stated assumption).

**The input is the problem.** Joining 798 published 10-06 anytime lines to the sim's player props (10 leagues):

- sim anytime / market fair: median **0.45**
- sim anytime IF PLAYING / market fair: median **0.62** -- so the per-player rate itself is low; minutes add the rest
- 552 of 798 are regulars (`expected_minutes_share` >= 0.6); 74 have < 0.25 (the Osorio shape: anytime 0.0028 = minutes
  share 0.0111 x if-playing 0.0995 while the market prices him as a regular) -- a minor contributor

**Not market margin, not team totals.**

- Per team, the players' `expected_goals` sum to the team's `team_projection.<side>_mean` exactly (median 1.000 in every
  league, 188 team-sides).
- Over 52 teams with >= 8 priced players, the market's fair prices imply those players carry **0.92** of the team's goals.
  The sim gives the SAME players **0.48**.
- The sim hands about half of every team's goals to players the books do not even price (bench, defenders, fringe). The
  match total is right; its split across players is far too flat.

This is the same bias lane `soccer-shots-allocation-blend` measured for shots: regular starters under-projected (0.858 vs 1.101
actual), subs over-projected (0.646 vs 0.566). One allocation defect across goals and shots, not a scorer-market bug.

## Consequences, by consumer

- **Rank**: soccer scorer and SOT rows carry large NEGATIVE edges, so they sink. Where the edge is POSITIVE it is most likely a
  fringe player the flat allocation OVER-rates. Those are the rows most likely to be adverse selection.
- **Scorecard / optimizer `p_model`** (`fair + me/100`): soccer scorer cells read as a badly overconfident-negative model. Correct
  as a description; the calibration shrink would treat it as a scale problem when it is an allocation problem.
- **Portfolio**: `measured_market_skill` already scales soccer scorer stakes toward the 0.5 floor (anytime -29.5% at the price),
  and the 2026-10-06 fair-noise shrink takes market-only 1-2-book edges to ~0. Exposure exists only through positive model edges on
  fringe players.

## Fix proposal (not implemented -- the allocation file belongs to another lane)

1. **Concentrate the allocation** in `syndicate/features/soccer/sim_engine/soccersim/player_props.py` (held by
   `soccer-shots-allocation-blend`): weight each player's share of team goals and shots by expected minutes x position x own rate,
   so starters carry most of it. That lane's own-rate blend (`SYNDICATE_SOCCER_PROP_OWN_RATE_BLEND`, stage 2 of H38) is the natural
   vehicle; extend its measurement to GOALS. Pre-register a check: sim / market share of the priced players should move from 0.48
   toward ~0.9 without the team totals moving.
2. **Minutes for transfers** (the Osorio shape, 74 / 798): `expected_minutes_share` near 0 for a player the market prices as a regular.
   Lead for the lineups / roster lanes.
3. **Until fixed, a positive scorer/SOT edge is suspect**, not a bet. This needs no new gate: the existing `skill_reliability`
   scaling and the fair-noise shrink already hold stakes down. The fix must come from the model, never a market withhold
   (2026-10-05 PRIME DIRECTIVE).

## CORRECTION 2026-10-07 (lane `soccer-goal-allocation`) -- the "0.48 vs 0.92" market comparison overstated the gap; the outcome-graded error is goals on players who do not appear

- **What was wrong.** The 0.92 "market-implied share of team goals" and the "sim anytime = 0.45x market" ratio used the board's `fair_probability` for ONE-SIDED scorer props. That fair is `book_margin_model` with an assumed hold of about 6-7% (`edge_vs_modelled_fair_hold_pct` 6.098 / 7.417 on the rows above). Scorer markets carry far more overround: a median-over-books vigged market share computed on 87 matches came out at 2.03 of team goals, which is impossible. So those fairs OVERSTATE the market's probability, and both figures exaggerate the sim's shortfall. The units finding (`me` is absolute pp) and the per-team sum check (players' xG = team xG) stand.
- **What the outcomes say** (H40 fit, 5,882 LISTED players, 119 matches, 7 dates 09-17..09-30, goals from the backfilled log):
  - the current model puts **58.3 of 355 expected goals on players who did not appear** (they scored 0);
  - players who appeared run 1.16x actual/model (starters 1.11x, subs 1.53x);
  - by band: < 0.02 -> 2.38x, 0.30+ -> 0.84x.
  The board's unconditional scorer probability is mostly wrong about WHO APPEARS, not about how goals split among regular starters.
- H40 (shrunk xG/90 x start-weighted minutes) is NOT SUPPORTED: details are in the lane block. A post-hoc variant with an as-of P(appear) term did beat the current model (NLL CI [-0.0123, -0.0007]) but must be pre-registered and tested on fresh dates.
