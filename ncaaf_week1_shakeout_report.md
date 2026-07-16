# SmartSim 2.0 NCAAF Week 1 Shakeout Report

- Date: 2026-07-15
- Scope: operational shakeout only — runs the frozen `NCAAF_CALIBRATION_PROFILE` v1 (Experimental, per `ncaaf_calibration_profile_report.md` / `ncaaf_profile_validation_report.md`) against a real upcoming schedule end-to-end. **No simulator, Football Core, NFL profile, or NCAAF profile changes were made.**
- Games: CFBD `/games?year=2026&week=1&seasonType=regular` — 99 scheduled games, **51 FBS-vs-FBS** (same quality-skew filter as the truth layer; 48 excluded as FBS-vs-FCS "buy games"), kickoff dates 2026-08-29 through 2026-09-07. All 99 games are `"completed": false` — this is a genuine future schedule, not a backtest against known results.
- Method: one `simulate_game(simulation_input, profile=NCAAF_CALIBRATION_PROFILE)` call per game, deterministic per-game seed (`zlib.crc32(game_id)`, matching the existing `baseline_audit.py` convention), **neutral inputs** (0.0 offense/defense ratings, no `feature_generation_payload` beyond game/season/week identifiers) — because, as already documented in `ncaaf_profile_validation_report.md`, **no NCAAF team-strength feature feed is wired yet** (unlike NFL, which has `games_details.csv`/EPA/pace). This is the same limitation, not a new one; it is called out again here because it directly shapes how per-game scorelines should be read (see below).
- Reused, unmodified: `summarize_simulation_outputs` and `summarize_simulated_drive_outcome_frequencies` (`calibration/evaluation_metrics.py`) for aggregation, so these figures are directly comparable to the 4,000-game validation pass on an apples-to-apples basis.

## Task 1-2: Aggregate Outputs (51 games, 1,032 drives)

| Metric | NCAAF Truth | NCAAF Sim (validation, 4,000 games) | NCAAF Sim (**Week 1 shakeout, 51 games**) |
| --- | --- | --- | --- |
| Possessions/game | 23.65 | 20.17 | 20.24 |
| Plays/drive | 5.77 | 7.21 | 7.18 |
| Yards/drive | 42.49 | 43.04 | 41.59 |
| Yards/play | 7.36 | 5.97 | 5.80 |
| Touchdown rate | 26.4% | 28.6% | 26.8% |
| Field-goal rate (made) | 10.0% | 10.8% | 10.0% |
| Punt rate | 35.1% | 26.2% | 25.6% |
| Turnover rate (incl. TOD, shared-evaluator convention) | 18.2% | 15.7% | 18.6% |
| Turnover-on-downs rate | 7.3% | 3.72% | 4.55% |
| Red-zone conversion rate | 85.6% | *(not measured in validation report)* | **72.6%** |
| Game totals | 53.35 | 46.90 | 44.08 |

**The 51-game shakeout reproduces the 4,000-game validation run's distribution closely on every metric** (differences are within normal small-sample noise — e.g., game totals 44.08 vs 46.90 is well inside the spread expected at n=51 vs n=4,000). This is itself a useful confirmation: the profile behaves consistently on a fresh, real schedule rather than only on the synthetic seed sweep used for validation.

### Drive outcome distribution (1,032 simulated drives)

| Outcome | Share |
| --- | --- |
| touchdown | 26.8% |
| punt | 25.6% |
| field_goal | 10.0% |
| missed_field_goal | 8.1% |
| turnover | 14.1% |
| turnover_on_downs | 4.6% |
| end_of_half_stop | 8.6% |
| end_of_quarter_stop | 2.2% |

### Totals and margin distribution (51 games)

| | Min | Median | Mean | Max | Stdev |
| --- | --- | --- | --- | --- | --- |
| Game total | 23 | 45 | 44.08 | 76 | 12.14 |
| Margin | 0 | 7 | 10.63 | 35 | — |

## Task 4-6: Red-Zone Finding (New)

The 51-game sample's red-zone conversion rate (72.6%) was far enough below NCAAF truth (85.6%) to check for small-sample noise before reporting it. A 1,500-game neutral-input replay (same method as the validation report) confirms it is **not noise**:

| | NCAAF Sim (1,500 games) | NFL Sim (1,500 games, same method) | Respective Truth |
| --- | --- | --- | --- |
| Red-zone conversion rate | **76.4%** | 84.4% | NCAAF 85.6% / NFL ~85-88% |

NFL's own profile reproduces its red-zone conversion truth closely (as already established in `nfl_production_candidate_report.md`). NCAAF's does not — an ~11-point, ~13% relative gap that **the validation report never measured** (its Task 10 comparison table omits a red-zone-conversion row entirely, even though the truth report explicitly flags red-zone conversion as one of the metrics that should be sport-invariant and Football-Core-transferable). This is the shakeout's main substantive finding.

**Diagnosis:** NCAAF's `explosive_play_multiplier` (1.45), `explosive_yardage_multiplier` (1.35), and `drive_yardage_multiplier` (1.15) raise how often a drive *reaches* the red zone (bigger plays traveling further downfield), but the profile has no compensating red-zone-specific efficiency lever — once inside the red zone, the shared (unmodified) `field_goal_range` stiffening logic in `play_simulator.py` (`gain *= 0.80`) interacts with NCAAF's now-larger explosive-play frequency in a way that produces more red-zone *entries* without a matched increase in red-zone *conversions*. This is the same class of "yardage levers reshape the population entering a decision point" dynamic already diagnosed for turnover-on-downs in `ncaaf_profile_validation_report.md` — not a new mechanism, but a previously unmeasured symptom of it.

**Category: NCAAF Profile issue.** Not Football Core (the identical, unmodified logic fits NFL well) and not a data issue (this is a pure simulator-output measurement, no external data dependency).

## Task 4-5: Other Unexpected Behaviors, Categorized

| Behavior | Category | Notes |
| --- | --- | --- |
| Red-zone conversion under-fit (72.6-76.4% sim vs 85.6% truth) | **NCAAF Profile issue** | New finding, diagnosed above. Not blocking (Experimental tier already accepts known residual gaps), but should be added to the v1 known-gaps ledger alongside turnover-on-downs and punt rate. |
| Individual scorelines look like upsets — e.g. San José State 42, USC 7; Missouri State 35, Texas A&M 9 | **Data issue** | Expected and correctly attributable to the absence of an NCAAF team-strength feature feed (documented since the validation report): every matchup is simulated with identical 0.0/0.0 offense-defense ratings regardless of real team quality, so all variance is pure RNG. This is not a Football Core or profile defect — it is the pre-existing, already-known gap that blocks any *predictive* (as opposed to structural) use of the profile. See "ready for live evaluation?" below. |
| Game totals and quarter-scoring shape run ~15-20% below truth (44.08 vs 53.35; Q2 12.31 vs 15.74 truth) | **NCAAF Profile issue (already known)** | Reconfirms, at real-schedule scale, the exact gap already diagnosed in `ncaaf_profile_validation_report.md` (yards/play lever only partially closes the totals gap). Not new. |
| Punt rate (25.6%) and turnover-on-downs rate (4.55%) both under-fit truth (35.1%, 7.3%) | **NCAAF Profile issue (already known)** | Reconfirms the documented "yardage levers shrink the population that ever reaches a contested punt/4th-down decision" trade-off from the validation report. Not new. |
| One game (San José State @ USC) flagged 3+ drives with yardage < -5 | Not an issue | Ordinary sack/penalty/turnover-return variance; no negative clock, no zero-play drives, no exceptions anywhere in the 51-game run. |
| Accented team name ("José") rendered as `Jos�` in one raw terminal echo during analysis | Not an issue | Console/terminal codepage artifact only; the underlying JSON output and `SmartSim2SimulationInput.home_team`/`away_team` strings are correct UTF-8 (`San José State`) throughout — confirmed by reading the JSON payload directly. No simulator or data-pipeline defect. |

## Anomaly Scan (all 51 games)

- Simulation errors / exceptions: **0**
- Drives with zero plays: **0**
- Games with negative clock_consumed: **0**
- Games with total > 90 or < 20: **0**
- Games ending outside quarter 4 / OT: **0**
- Drive-count outliers (<15 or >35 drives/game): **0**
- Games with >2 drives showing yardage < -5: **1** (ordinary variance, see above)

## Explicit Answers

**Which outputs look realistic?** Possessions/game (20.2 vs 23.65 truth — same ~15% undershoot already known and unchanged from the validation pass), yards/drive (41.6 vs 42.5 truth — excellent fit, consistent with the validation report calling this the "headline result"), touchdown rate (26.8% vs 26.4% truth — near-exact), field-goal rate (10.0% vs 10.0% truth — exact), and the combined turnover-rate convention (18.6% vs 18.2% truth — near-exact). The engine also ran cleanly: 51/51 games, 0 exceptions, 0 structurally invalid drives, every game reaching a normal quarter-4-or-overtime conclusion.

**Which outputs look suspicious?** Two things, both explained rather than mysterious: (1) red-zone conversion at 72.6-76.4% vs 85.6% truth — a genuine, newly-surfaced profile gap (see above); (2) several individually lopsided scorelines against real 2026 team names — these are an artifact of simulating every matchup with identical neutral ratings, not a defect in the engine or profile.

**Are there profile-level calibration gaps?** Yes, one new one (red-zone conversion, diagnosed above) plus three already-documented ones reconfirmed at real-schedule scale (game totals/quarter shape, punt rate, turnover-on-downs rate). None of these required or suggested a Football Core change; all are addressable, if pursued, as additional or adjusted `CalibrationProfile` fields in a v2 pass.

**Is NCAAF Profile v1 ready for live evaluation?** Split answer, matching the "Experimental" tier already assigned: **yes for continued structural/operational shakeout** — the profile-selection architecture, the shared engine, and the full CFBD-schedule-to-simulated-output pipeline all work end-to-end on a real, unseen schedule with zero errors and no Football Core changes required. **Not yet for live scored predictions** — the blocking gap is the same one the validation report already named (no NCAAF team-strength feature feed), now confirmed to matter in practice: every one of these 51 real games was simulated as a talent-neutral coin flip, so any scoreline or total attached to a real matchup right now would be structurally uninformative about that specific game, independent of how well the aggregate distribution fits truth.

## Success Criteria

**Met.** The simulator completed a full Week 1 run (51/51 FBS-vs-FBS games from the real 2026 CFBD schedule) with zero exceptions and zero Football Core modifications — only the pre-existing `profile=NCAAF_CALIBRATION_PROFILE` argument was used, exactly as built.
