# H3 — player-prop history term in the Layer 2 score: INCONCLUSIVE (no score change)

Lane `intelligence-evidence-coverage`. Pre-registered 2026-10-08 in `lanes.md` (commit `35fe6124`) before any
number; exploratory MLB addendum `d0e4a7f2`. Harness `C:\tmp\l2score_h3\` (`features.py`, `soccer_features.py`,
`mlb_splits_asof.py`, `h3.py`); full output `C:\tmp\l2score_h3\h3_output.txt`, run 2026-10-08 ~16:25Z.

## Rule (as registered)
Term T = 100 x (R + V + D) on prop rows (over/under, numeric line); R = shrunk hit rate of the row's side over
the last <= 10 games (n >= 3), V = same vs this opponent (n >= 1), D (NFL, WNBA) = 0.05 x clip(z, +/-2) of the
opponent's per-game allowed to the position; all from games strictly before the SIGHTING date. Variant
sc + clip(0.1 x T, +/-1.5) vs live sc; top 25 per date x sport, <= 3 per game, fee-net CLV, bootstrap over games
(2000, seed 20261008). MET iff overall lo > 0 with >= 50 games and no sport with >= 50 games entirely < 0.

## Result
| | variant | live | diff (pp) | 95% CI | games | picks differ |
|---|---|---|---|---|---|---|
| **overall (deciding)** | +1.275 | +1.268 | **+0.007** | [-0.073, +0.091] | 358 | 103 of 1,303 |
| wnba | +2.256 | +1.905 | +0.351 | [-0.500, +1.291] | 24 | 24 |
| nhl | +1.349 | +1.312 | +0.037 | [-0.087, +0.176] | 85 | 16 |
| nfl | +1.602 | +1.688 | -0.086 | [-0.354, +0.196] | 33 | 61 |
| ncaaf | +1.029 | +1.037 | -0.008 | [-0.021, +0.000] | 101 | 1 |
| mlb | -0.052 | -0.067 | +0.014 | [+0.000, +0.045] | 86 | 1 |

**DECISION: INCONCLUSIVE -> no score change.** Sensitivity (reported only): w=0.05 +0.026 [-0.041, +0.095];
w=0.2 -0.017 [-0.124, +0.088]. Row-level slope of fee-net CLV on T: every sport's CI contains 0
(wnba +0.0055 [-0.0059, +0.0162], nhl +0.0040 [-0.0030, +0.0102], nfl -0.0018 [-0.0135, +0.0094],
ncaaf -0.0023 [-0.0064, +0.0021], mlb -0.0017 [-0.0336, +0.0012]).

Read: within this window, a player's recent hit rate, his history vs the opponent and the opponent's
allowed-to-position do not predict closing-line movement beyond what the live score already ranks on.
This is about CLV (the registered grade), NOT about whether the props win: an outcome-graded test was not
registered and is not claimed either way.

## Reachability (prop rows in the CLV-graded population with >= 1 component)
wnba 8,387/8,387 (100%; D 8,387) | nhl 7,699/9,112 (84.5%) | nfl 33,412/39,774 (84.0%; D 32,563, R 16,163 --
early season, n >= 3 binds) | ncaaf 11,866/12,549 (94.6%) | mlb 462/624 (74%) | nba 0 prop rows (preseason) |
**soccer 0 over/under prop rows in the graded population** (its graded props are scorer yes/no markets), so
the soccer history source -- built and featurised, 1,785/2,011 opening rows -- could not be tested here.

## Deviations, all made before any number was seen
1. Point-in-time enforced in the harness where production readers do not cut at the sighting date:
   basketball `_box_games` reads every box row (live-harmless, leaks in a backtest); NFL usage lines read all
   weeks (cut to weeks < the game's week); NCAAF box cut to (season, week) < the game's; NHL game log includes
   same-day games (first pass refused ~4,400 rows on the per-row assertion; re-run with the sighting-day cut);
   soccer appearances cut at the sighting day. Every row asserts its newest game < sighting date.
2. Sources built AFTER the registration, before any number: soccer player match log, NBA/WNBA multi-season
   player game log (WNBA V uses it), NCAAF vs-opponent hit rate + 2023-24 history (V was structurally empty --
   the provider counted meetings, no hit rate). Their sports were re-featurised and replace the first pass.
3. WNBA's opponent is derived from the player's newest box team when no sim row exists (the provider's
   matchup needs that day's sim row).
4. Exploratory (not deciding): MLB as-of hand split; starters for regular-season games taken from the pitches
   (fleet probables exist only from 10-01) -- a late scratch would leak. Only 249 graded MLB rows carried it:
   uninformative.

## What this does and does not change
- The history SENTENCES stay: they are explanation, served since 2026-10-08 15:23Z (deploys.md `0ee47701`).
- No score term. A re-test needs either an outcome-graded registration or a longer window (soccer over/under
  props and MLB props are thin in the CLV population).
