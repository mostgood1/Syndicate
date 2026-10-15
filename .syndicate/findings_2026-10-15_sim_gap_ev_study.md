# Sim gap x EV x outcome -- findings 2026-10-15

Lane `sim-gap-ev-study` (session 9e18a0e7). Pre-registered in the lane block at `ca52ea13` before any
run (H1-H3, signal rule, >= 30 games, game-clustered bootstrap). Two independent instruments:

- **One-off study** (subagent, scratch scripts, production's own grader over the recorder plus the
  evaluation ledger's raw `model_probability`). Population: scorecard unit (sport, key, phase),
  earliest qualifying sighting, two-sided fair + price + outcome + sim. 84,344 bets, 09-30..10-14.
- **Daily instrument** (`syndicate/features/shared/sim_gap_ev_study.py`, riding the `model-scorecard`
  cron since `cce22975`) and its **backfill** (`scripts/sim_gap_ev_study.py`): 476 games over 15 dates,
  09-30..10-14, recorder `me` only (no rows above 15 points). Run 1 (/1) pooled fair types; /2 splits them.

Every number below carries its population. "Brier diff" = Brier(sim) - Brier(market) per row,
positive = the sim is worse. "w" = Brier-optimal weight in fair + w * (sim - fair). "slope" = least-
squares slope of outcome on the sim's probability, 1 = right, < 1 = overconfident.

## Betting (A): the sim agreeing does not make a bet better

- **H1 stands.** One-off: 18 eligible sport x phase x EV tests, 16 no separation; the 2 exceptions are
  artifacts (ncaaf live-resim EV10+ = Polymarket in-play quotes at +1,900..+4,900; ncaaf pregame EV10+,
  20 vs 37 bets). Staked orders (P2, 1,761 distinct bets of 4,131 settled): 0 of 9 eligible cells pass,
  H1 stands 5/5. Backfill /1: 8 of 9 clean comparisons no difference; the 9th (soccer pregame EV<0,
  FOR beats AGAINST +42.8 pts [+23.2, +65.2]) is absent from the two-sided-only one-off run
  (+3.1 pts [-15.0, +20.6]) -- the fair-type confound that /2 now splits.
- **No sim-gap pocket.** One-off: 654 cells, 77 with >= 30 games; against each cell's own market EV
  4 of 77 pass vs ~3.9 expected by chance (3 negative, 1 positive: ncaaf live-resim 0-2 FOR, 55
  bets / 33 games). 81,510 of 84,344 bets (96.6%) are EV < 0, so gap x EV is effectively one column.
- **The only positive-ROI pockets are live, EV10+, no sim** (backfill /1: ncaaf live nosim EV10+ 115
  games / 678 bets ROI +150.6%; nfl live nosim EV10+ 31 games / 524 bets +96.3%). One-off: EV10+ live
  is 62% exchange-quoted (9% in EV<0) and 21.5% of those bets claim EV > 50% -- not executable.
- **H3 stands (one-off, via the evaluation ledger).** 18 groups with >= 20 rows above 15 points: the sim
  is worse than the market in 18/18 (CI > 0 in 10). The board's `_MODEL_EDGE_MAX_POINTS = 15` drop is
  doing its job. The daily instrument cannot see these rows (the recorder writes `me` = None above 15).

## Engine (B): where the sims are wrong

| sport, pregame | games | Brier diff (one-off / backfill) | w | slope sim (one-off / backfill) | read |
|---|---|---|---|---|---|
| nfl | 31 / 30 | +0.010 [0.003, 0.018] / +0.012 | ~0 | 0.25 [0.09, 0.44] / 0.40 [0.04, 0.75] | overconfident ~2.5-4x, mean unbiased |
| ncaaf | 118 / 106 | +0.012 [0.006, 0.018] / +0.008 | ~0 | 0.34 [0.17, 0.49] / 0.51 [0.03, 0.97] | overconfident; spreads 0.35, totals 0.08, h2h 0.89 |
| nhl | 93 / 93 | +0.005 [0.001, 0.008] / +0.004 | ~0 | 0.98 [0.84, 1.13] / 1.02 [0.93, 1.12] | shape right, no information beyond the line; sog slope 0.37 |
| soccer | 130 / 110 | +0.012 [0.001, 0.025] / -0.002 | -0.05 / 0.65 | 0.59 [0.35, 0.86] / 1.00 | DISAGREE: one-off two-sided only, backfill /1 pooled one-sided fairs |
| mlb | 24 / 24 | +0.003 / +0.004 | ~0 | 1.39 / 1.10 | thin, postseason |
| nba | 41 / 41 | -- | -- | -- | preseason; sim == market on 5,590 of 6,492 rows |
| wnba | 10 / 10 | +0.004 / +0.004 | -- | 1.14 / 1.06 | too few games |

- **Mean vs spread.** No pregame mean bias at the 50/50 line in any sport (CIs span 0). The defect is
  extremity: football probabilities sit 2.5-4x too far from 0.5. The one-off could not separate "sigma
  too narrow" from "mean inputs noisy". Recalibrating removes the overconfidence; with w ~ 0 the sim
  would still add nothing beyond the market until its INPUTS improve.
- **H2 (w falls with gap) not supported** broadly: one-off 15 of 17 sport-phase contrasts inconclusive;
  supported for soccer pregame (w 2.33 at 0-5 -> 0.06 at 10+, 130 games), falsified for wnba live.
- **Lead time.** No consistent late staleness, except soccer: < 1 h +0.063 [0.005, 0.135] (28 games),
  2-6 h +0.029, > 6 h +0.004 (one-off).
- **Live re-sim is worse than the market everywhere** (one-off): nfl +0.124 [0.041, 0.213] (15 games,
  slope -0.13), ncaaf +0.035, soccer +0.033 (bias +14.5 pts), wnba +0.023.
- **Props over-rate** (one-off): NHL saves +10.0 pts [0.4, 18.8] (66 games), NHL goals +4.5, MLB pooled
  +9.6 (24 games); the market is similarly high.

## Defects (verified against code where marked)

1. **NHL puckline orientation -- VERIFIED IN CODE.** `nhl/game_projections.py` `_game_projection`
   spreads branch stamps P(home -1.5) with `side = home` on ANY row whose line is -1.5; for an
   away -1.5 row `layer2_board` (~2690-2707) serves `1 - P(home -1.5)` = P(away +1.5). 42 rows / 21
   games, impossible in 21/21 (sim away -1.5 0.764 vs sim away ML 0.543 vs fair 0.340). Spun off as
   task `task_161821da` (user started it in a separate session 2026-10-15).
2. **Soccer first-half totals priced as full game -- ALREADY FIXED 10-13** (lane
   `soccer-segment-projection-guard`). The study's 10 such rows are 10-10..10-12, before the fix: an
   independent re-find, not a new defect.
3. **NFL live-carried numbers** (one-off, UNVERIFIED mechanism): 12,001 of 22,975 NFL bets (52%) carry
   the pregame sim on an in-play line; slope -0.02 there.
4. **NBA sim == market** on 86% of preseason rows (one-off, UNVERIFIED mechanism): an absent view
   replaced by the market.
5. **Prop role/usage extremes** (one-off, HYPOTHESIS): 8 NFL unders at sim 0.80-0.999 vs fair 0.26-0.50
   on players who went over; MLB Hagen Smith outs-under sim 0.003; NHL Hoglander goals-under 0.045.

## Instrument amendments (recorded in `PREREGISTRATION["amendments"]`)

- Registered signal "ROI CI excludes 0" measured the vig: backfill /1 tested 300 cells, 149 passed,
  146 negative, 142 of those in EV < 0. Headline is now realised ROI minus the cell's own mean EV.
- Fair type is part of every cell (two_sided / one_sided / other / unknown); /1 states reset.

## Not computed

- Rows above 15 points for UNPUBLISHED sides: the raw sim is persisted nowhere (~36% of 15+ recovered).
- Per-market fits where < 30 games (MLB, NBA live, NHL live) pool to sport level.
- Fee-net ROI (fee-net EV applies to 7.4% of bets; ROI gross).
- Input-level attribution: defect classes name modules only.
