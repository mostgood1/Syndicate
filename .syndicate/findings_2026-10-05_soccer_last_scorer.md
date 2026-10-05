# Last goalscorer: why it loses more than first, and whether a time-aware race fixes it — 2026-10-05

Lane `soccer-last-scorer-pricing` (session b9bb5f37). Data: the 10-02 props cache
(`C:/tmp/soccer-lpb/cache`), ESPN summaries in `%TEMP%/espn_shots_cache` (712 full time).
Scripts, all in `scripts/soccer_season_audit/`: `last_scorer_study.py`, `last_scorer_timed_race.py`,
`last_scorer_price_test.py`. Baseline: `findings_2026-10-05_soccer_scorer_race_grade.md`
(last scorer ROI on EV>0 -66.8% [-92.4, -31.5]).

## 1. The goal record (667 matches with a non-own goal)

| | first goal | last goal |
|---|---|---|
| scored by a substitute | 4.5% | 35.7% |
| median minute | 23 | 78 |
| game state before the goal | level (601 of 601) | level 193 / leading 209 / trailing 199 |

## 2. The board's race by role (300 matches, appeared players, realised / model-expected)

| | first scorer | last scorer |
|---|---|---|
| starters | 1.33 [1.22, 1.44] | 0.90 [0.78, 1.02] |
| substitutes | 0.07 [0.00, 0.18] | 2.10 [1.61, 2.64] |

The hypothesis is CONFIRMED. `soccer_scorer_markets`' docstring says late-match rate changes "cancel out
of the RELATIVE shares". That is false, because WHO is on the pitch changes. (Role is conditioned on the
realised appearance, so both roles carry selection; the first-vs-last contrast within a role is what
carries the signal.)

## 3. Time-aware race, out of sample

Mechanism: each player keeps the board's per-match rate, spread over minutes by
`goal intensity g(t) x on-pitch o_p(t)`, where `o_p = w(minutes share) x starter curve + (1 - w) x sub curve`.
Curves measured from ESPN substitution minutes (starters on at 60' 0.91, at 85' 0.62; subs 0.22 / 0.91);
goal intensity first 15' / last 15' = 0.54. `w` is fitted on post-09-07 builds only: the minutes field
changed with the 09-07 model version, and fitting on older builds inverted `w`.

Fit before 09-16; scored on/after (post-09-07 builds), 122 matches, appeared players:

| | log-loss, current | log-loss, time-aware | difference [CI] |
|---|---|---|---|
| last scorer | 0.14787 | 0.14496 | **-0.00292 [-0.00407, -0.00182]** |
| first scorer | 0.12881 | 0.12948 | +0.00067 [+0.00004, +0.00139] |

The substitute miss barely moves (last scorer, subs 3.31 -> 2.92): pre-match data can't say who will
come off the bench. `expected_minutes_share` separates roles only loosely.

## 4. At the price (last scorer only, same lines, 8 dates / 81 matches / 1,837 lines)

| | EV>0 bets (wins) | ROI [CI] | log-loss |
|---|---|---|---|
| current race | 198 (7) | -55.7% [-89.3, -10.0] | 0.13698 |
| time-aware race | 167 (6) | -51.4% [-90.1, +3.6] | 0.13417 |

ROI difference, time-aware minus current: [-5.7, +15.7], not significant. Log-loss difference
[-0.00444, -0.00132], significant.

## Verdict

- The time-aware race is a REAL but SMALL improvement for last scorer, and slightly worse for first. It
  does NOT make last scorer bettable: both versions lose heavily at the price.
- It is NOT SHIPPED. It would add three fitted inputs to an engine; under
  `docs/ai_context/model_engine_standard.md` that needs an input checklist, a pipeline trace and a
  reachability test, and the measured ROI gain is not significant.
- The live mitigation is the registry: last scorer is registered as `loses_to_market`
  (established_loss_rel 0.315) by lane `layer2-unmeasured-per-line`, so it ranks and stakes at the 0.5
  floor.
- The fix that would matter is knowing the bench. That means lineup and bench information before
  kickoff, which the producer doesn't carry today.
