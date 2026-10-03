# Soccer lines + props backtest — 2026-10-02 (lane `soccer-lines-props-backtest`)

Full write-up, method and caveats: `.syndicate/findings_2026-10-02_soccer_lines_props_backtest.md`.
All numbers: `lines_props_backtest_2026-10-02.json`. CI = match-clustered bootstrap, 95%.

**Gate (NHL template: beat the naive as-of baseline AND the de-vigged book) — passing markets: none.**

## 2026-27 pregame game lines (07-22..09-20, MLS to 09-30; production builds; football-data close)

| market | n | vs naive as-of | vs book | gate |
|---|---|---|---|---|
| 1X2 (3-way Brier) | 671 | −0.0320 [−0.0494, −0.0141] beats | +0.0285 [+0.0169, +0.0411] loses | fail |
| draw (two-way) | 671 | +0.0002 [−0.0026, +0.0031] | +0.0017 [−0.0008, +0.0042] | fail |
| Asian handicap | 458 | — | +0.0208 [+0.0082, +0.0340] loses | fail |
| O/U 2.5 | 492 | — | +0.0095 [+0.0032, +0.0157] loses | fail |
| total goals MAE | 712 / 492 | −0.0207 [−0.0472, +0.0063] | +0.0521 [+0.0233, +0.0810] worse than book mean | fail |
| BTTS | 487 | — | +0.0060 [+0.0006, +0.0116] loses | fail |
| team goals (log loss) | 492 | — | +0.0430 [+0.0251, +0.0620] loses | fail |
| corners total, sim | 444 | +0.030 [−0.007, +0.067] | main line +0.0089 [−0.0002, +0.0185] | fail |
| corners total, estimator (09-17+) | 89 | −0.065 [−0.175, +0.036] | H27 forward, grades 11-15 | fail (under-powered) |
| cards, first/last scorer | — | not projected | — | untestable |

## 2026-27 player props, post-fix builds (pre-kickoff only; 119 matches, 09-17..09-30)

Baseline c = player's own as-of per-appearance mean shrunk to the league mean (3 pseudo-apps).

| market @ line | n rows | ΔBrier vs c | ΔLogLoss vs c | book (one-sided): ROI model EV>0 |
|---|---|---|---|---|
| shots 0.5 / 1.5 / 2.5 | 3,003 | −0.0012 / **+0.0068** / +0.0020 | **+0.046 / +0.036** / +0.007 | −22.4% [−40.6, −1.7] |
| SOT 0.5 / 1.5 | 3,003 | **−0.0048** / −0.0013 | −0.001 / −0.007 | −7.1% [−41.3, +31.1] |
| anytime | 3,003 | **−0.0028 [−0.0051, −0.0006]** | **−0.0169 [−0.0279, −0.0059]** | −29.5% [−53.7, +0.8] |
| assists 0.5 | 2,736 | −0.0009 | −0.0075 | −8.4% [−47.0, +34.8] |

## 2025-26

1X2 loses in 8 of 9 leagues (08-15, n 1,112, pre-close benchmark). Totals/draw/true-close re-run owed
(host saturated); harness extended and smoke-tested.
