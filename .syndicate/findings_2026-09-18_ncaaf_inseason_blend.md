# NCAAF in-season rating blend — backtest and first production run (2026-09-18)

Lane `ncaaf-sim-inseason-ratings`, session 259d6003. The backtest was run by this session's subagent (`scripts/backtest_ncaaf_inseason_blend.py`, landed `9fbac1f6`); the numbers below are its report, restated -- not re-derived here. Production readings are this session's own (`deploys.md` 2026-09-18 23:16:09Z).

## Coverage
- Local git-tracked `historical_truth` (games, per-play PPA, drives) + `cfbd_lines_*` closes + CFBD `/ppa/games` (8 CFBD calls). Rated FBS-vs-FBS games with every family present: **634 / 654 / 644** in 2023 / 2024 / 2025, every one with a close. Tuned on 2023+2024; graded ONCE on held-out 2025 weeks 3-15 (**644 games**). 300-seed Monte Carlo through the production `build_projection`; an analytic surrogate (corr 0.987-0.993 vs Monte Carlo) was used for tuning only.

## Result (held-out 2025 weeks 3-15, margin MAE vs actual)
| arm | MAE | dMAE vs baseline [95% CI, bootstrap over games] |
|---|---|---|
| baseline: static prior-season SP+ (the leak-free stand-in for the current generator) | 16.334 | -- |
| **blend_ppa[k=2]**: prior SP+ blended with season-to-date per-game PPA, weight n/(n+2) | **12.830** | **-3.50 [-4.33, -2.68]** |
| closing spread | 11.900 | blend still +0.93 [+0.55, +1.32] behind; w = +0.04 [-0.18, +0.25] |

By week: 3-5 -2.28 [-3.85, -0.77]; 6-9 -3.79 [-5.21, -2.32]; 10-15 -3.91 [-5.20, -2.61]. On the surrogate the blend also beats the best pure rescale of the prior by -1.37 [-2.10, -0.64], so it is not only a dispersion fix. Plays-derived PPA (r 0.935 vs CFBD `/ppa/games`) picked the same winner.

## Decision
The pre-registered rule (ship only if the held-out margin dMAE CI lies entirely below 0) is MET, so the blend shipped default-on from week 3 (`SYNDICATE_NCAAF_INSEASON_BLEND=off` reverts it with a deploy). It still does not beat the close, so picks stay suppressed.

## What this does NOT establish
- It was compared with prior-season SP+, not with production's refreshed 2026 SP+: no historical weekly SP+ snapshots exist, so that comparison is forward-only (`todo #677`).
- **Totals were not measured.** On 2026 week 3 the blend moved total means by 7.80 points on average (max 25.89) -- e.g. North Texas @ Texas State 91.9 -> 96.2 against a 63.5 line. Grade totals against the close alongside margins before trusting them.
- The live re-sim still prices off SP+ (`todo #678`).

## First production run
`INSEASON_BLEND season=2026 week=3 status=applied k=2 beta=44.497 prior_season=2025 teams=138 teams_with_games=138 ppa_rows=285` (refresh-worker 23:16:15Z); web's wk3 CSV `rating_source` names `inseason_blend_ppa` on 57/57. Week 3 margins moved by 9.96 points on average and the cross-game margin SD fell 19.94 -> 15.81.
