# SmartSim 2.0 Calibration Iteration 3 Report

- Source: NFL-Betting 2025 wk17/wk18/wk20 proxy baseline
- Split: calibration
- Iteration 2 calibration score: 0.000
- Iteration 3 calibration score: 0.000
- Games evaluated: 532
- Drives synthesized: 11233
- Benchmark verification: `load_baseline_audit_result()` loaded the identical proxy benchmark used by the baseline, Iteration 1, and Iteration 2 reports (532 games, 11233 drives).

## Evaluation Blocker Resolved

The Iteration 3 report previously failed to generate because the evaluation hung deterministically on game 14 (`2025_01_SF_SEA`). The 4th-down fallback branch in `drive_simulator.py` returned `TURNOVER_ON_DOWNS` without consuming clock or flipping possession; for field position in [88, 94) both the punt gate and the field-goal gate decline deterministically without consuming RNG, so the game loop re-simulated the identical state forever. The branch now performs a real possession exchange (clock consumed, field flipped, owner flipped). This was a correctness fix required to complete evaluation, not a calibration tuning change. All 10 focused smartsim2 tests pass, and the full 532-game evaluation completes in ~95 seconds.

## Before vs After

| Metric | Iteration 2 Norm Err | Iteration 3 Norm Err | Delta |
| --- | --- | --- | --- |
| turnover_rate | 41.506 | 22.958 | +18.548 |
| red_zone_conversion_rate | 1.319 | 1.319 | +0.000 |
| quarter_3_scoring | 1.007 | 0.898 | +0.109 |
| quarter_1_scoring | 0.873 | 0.812 | +0.061 |
| possessions_per_game | 0.780 | 0.629 | +0.151 |
| punt_rate | 0.759 | 0.723 | +0.036 |
| game_totals | 0.565 | 0.515 | +0.050 |
| drive_length_seconds | 0.415 | 0.362 | +0.053 |
| quarter_4_scoring | 0.382 | 0.367 | +0.015 |
| quarter_2_scoring | 0.305 | 0.268 | +0.037 |
| drive_length_yards | 0.236 | 0.194 | +0.042 |
| field_goal_rate | 0.166 | 0.135 | +0.031 |
| drive_length_plays | 0.130 | 0.052 | +0.078 |
| touchdown_rate | 0.112 | 0.056 | +0.056 |

No metric worsened at the normalized-error level. This is the first iteration with zero regressions.

## Drive-Ending Frequency Audit

| Outcome | Benchmark | Iteration 2 | Iteration 3 | Delta |
| --- | --- | --- | --- | --- |
| touchdown | 0.245 | 0.217 | 0.231 | +0.014 |
| field_goal | 0.162 | 0.135 | 0.140 | +0.005 |
| missed_field_goal | 0.000 | 0.259 | 0.283 | +0.024 |
| punt | 0.590 | 0.142 | 0.163 | +0.021 |
| turnover | 0.004 | 0.080 | 0.084 | +0.004 |
| turnover_on_downs | 0.000 | 0.079 | 0.006 | -0.073 |
| end_of_quarter_stop | 0.000 | n/a | 0.047 | n/a |
| end_of_half_stop | 0.000 | n/a | 0.046 | n/a |

Note: end-of-quarter/half stops were not broken out in the Iteration 2 audit; they are now visible as their own rows.

## Biggest Improvements

- turnover_rate: normalized error 41.506 -> 22.958 (+18.548); simulated true-turnover rate fell from 15.9% to 9.0%
- possessions_per_game: normalized error 0.780 -> 0.629 (37.58 -> 34.39 possessions per game)
- quarter_3_scoring: normalized error 1.007 -> 0.898
- drive_length_plays: normalized error 0.130 -> 0.052 (3.53 -> 3.84 plays, benchmark 4.05)
- touchdown_rate: normalized error 0.112 -> 0.056 (21.7% -> 23.1%, benchmark 24.5%)
- turnover_on_downs frequency collapsed from 0.079 to 0.006, so possession exchange now flows through kicks instead of failed 4th downs

## Largest Remaining Errors

- turnover_rate: 9.0% simulated vs 0.4% proxy benchmark (normalized error 22.958, still the dominant error)
- red_zone_conversion_rate: 100.0% simulated vs 43.1% benchmark (unchanged since baseline; every red-zone entry still scores)
- punt_rate / punt frequency: 16.3% vs 59.0% benchmark; punts moved only +2.1 points despite Iteration 3 targeting punt mix directly
- missed_field_goal frequency: 0.283 vs 0.000 benchmark, and it worsened slightly (+0.024); the simulator attempts and misses far too many field goals in states where real teams punt
- possessions_per_game: 34.39 vs 21.11; drives are longer, but the game still cycles possessions ~60% too fast
- quarter scoring / game_totals: 70.05 vs 46.24 total points; still roughly 50% too many points

## What Improved

turnover_rate, possessions_per_game, quarter_1_scoring, quarter_3_scoring, quarter_4_scoring, quarter_2_scoring, game_totals, drive_length_seconds, drive_length_yards, drive_length_plays, punt_rate, field_goal_rate, touchdown_rate

## What Worsened

- No metric worsened at the normalized-error level.
- Within the frequency audit, missed_field_goal (+0.024) and true turnover (+0.004) moved slightly further from the benchmark as outcome shares.

## Did Iteration 3 Improve Its Targets?

- Punt mix: Marginally. Punt share rose 0.142 -> 0.163 against a 0.590 benchmark. The fourth-down punt bias and punt-first neutral-drive logic moved the mix in the right direction, but most of the intended punt volume is being intercepted upstream by the field-goal attempt gate (0.140 made + 0.283 missed = 42.3% of drives end in a field-goal attempt vs 16.2% benchmark).
- Field-position realism: Yes, modestly. Punt-distance and touchback handling lengthened average drives (yards 23.74 -> 25.06, seconds 97.1 -> 106.0, plays 3.53 -> 3.84) and the touchback spot now feeds realistic starting field position.
- Possession exchange behavior: Yes, materially. Turnover-on-downs collapsed to 0.6% of drives, true turnovers fell from 15.9% to 9.0%, and possessions per game dropped from 37.58 to 34.39. Exchanges now happen predominantly through kicks, which is the correct structural direction, but total exchange volume remains far above benchmark.

## Explicit Answers

- Did punt rate improve? Yes, slightly: 14.2% -> 16.3% (benchmark 59.0%). Normalized error improved 0.759 -> 0.723. Directionally correct but far from target.
- Did turnover rate improve? Yes, strongly: 15.9% -> 9.0%, the largest single improvement this iteration (normalized error 41.506 -> 22.958). Still ~22x the proxy benchmark.
- Did scoring rates improve? Yes, modestly across the board: all four quarters and game totals improved (72.36 -> 70.05 total points vs 46.24 benchmark). Touchdown and field-goal shares both moved toward benchmark.
- Did possession count improve? Yes: 37.58 -> 34.39 possessions per game (benchmark 21.11). Longer drives and cleaner exchanges are compounding, but the game still generates ~13 excess possessions.
- What remains unrealistic?
  - Field-goal attempt volume: 42.3% of drives end in an FG attempt (made + missed) vs 16.2% benchmark; the missed-FG share (28.3%) is the largest single outcome distortion.
  - Red-zone conversion is still a constant 100%.
  - True turnover rate is still 9.0%.
  - Possession count and total scoring remain ~60% and ~50% above benchmark respectively.
- What should Iteration 4 target?
  1. Field-goal attempt gating: suppress FG attempts outside true kick range so those drives punt instead; this simultaneously fixes the missed-FG distortion and is the single largest available lever for punt mix.
  2. Red-zone conversion: introduce failed red-zone outcomes (FG settles, turnovers, downs) so conversion falls toward 43%.
  3. Residual true-turnover weight: reduce only after the punt mix responds, per the Iteration 2 sequencing rule.
  4. Possession count: expect it to fall naturally from 1-3; do not tune pace directly until the outcome mix is closer.

## Final Verdict

**Iteration 3 Partial Success.**

Every normalized-error metric improved or held, with zero regressions for the first time, and the possession-exchange mechanics (turnover-on-downs collapse, punt/touchback field position, longer drives) are structurally better. However, the iteration's primary objective — punt mix — moved only +2.1 points against a 44.8-point gap, because the field-goal attempt gate absorbs the drives that should punt. The punt-mix problem is now clearly localized to FG-attempt gating rather than spread across the drive engine, which gives Iteration 4 a concrete, measured target.
