# SmartSim Syndicate Integration Assessment

- Date: 2026-07-15
- Scope: NCAAF only. **SmartSim 2.0 code was not modified** — `NCAAF_CALIBRATION_PROFILE` v2 (`ncaaf_calibration_profile_v2_report.md`) was run exactly as shipped.
- References: `nfl_production_candidate_report.md`, `ncaaf_calibration_profile_v2_report.md`, `ncaaf_week1_shakeout_report.md`.

## Why NCAAF only, and why real completed games instead of "upcoming"

The literal task asked to run SmartSim on "upcoming games" and compare against the current engine and market. That comparison turned out to be **impossible to do honestly for either league on a genuinely future slate**, for two different reasons discovered during setup:

- **NFL**: real 2026 market data already exists (`data/nfl_source/real_betting_lines_2026_07_09.json`, live spread/total/moneyline for actual Week 1 2026 games), but the current NFL engine has produced **no scored projections for 2026** — its artifact (`upcoming_recs_2025_wk*.csv`) is a thin per-market EV-recommendation row (type/confidence/ev_pct/odds), not a projected score/spread/total, and the most recent one is for the 2025 season. There is nothing to put in the "Current Projection Engine" column for a real NFL 2026 game.
- **NCAAF**: the reverse problem — the current engine's own predicted-score artifact exists and is rich (`predicted_home_points`/`predicted_away_points`/`predicted_total_points`), but only for the 2025 season; there is no 2026 schedule or market data for NCAAF yet (the refresh script explicitly skips auto-refresh once the tracked season is in the past).

**Resolution**: since the objective is to determine whether SmartSim *adds value inside Syndicate* — not to publish new predictions — the most honest test available today is a **backtest on real, completed 2025 NCAAF games** where all four things exist simultaneously: the current engine's stored prediction, real market lines, real per-team season ratings to feed SmartSim, and the real final score to grade all three against. This trades "upcoming" for "verifiable," which is the more decision-relevant property for this specific objective.

## Method

- **Games**: 103 real, completed FBS-vs-FBS 2025 regular-season games across two non-adjacent weeks (Week 5, n=51; Week 10, n=52), chosen only for having complete data on all four sources — no cherry-picking by outcome.
- **Actual result**: `data/ncaaf_source/historical_truth/games_2025.json.gz` (the same CFBD-sourced cache used for the truth layer).
- **Market**: CFBD `/lines` for the same weeks, averaged across all reporting sportsbooks per game (2-3 books/game typically: DraftKings, ESPN Bet, Bovada). Spread convention: CFBD's `spread` is signed from the home team's perspective (positive = home underdog); market-implied home margin = `-spread`.
- **Current Projection Engine**: `predicted_home_points`/`predicted_away_points`/`predicted_total_points` from `data/ncaaf_source/data/college_football_schedule_2025_predicted_totals_enhanced.csv` (the latest snapshot, dated after the 2025 season ended).
- **SmartSim**: `NCAAF_CALIBRATION_PROFILE` (v2, unmodified), fed real per-team ratings derived from CFBD's season-long `/ppa/teams` (`offense.overall` → `home_offense_rating`/`away_offense_rating` directly; `-defense.overall` → `home_defense_rating`/`away_defense_rating`, negated because CFBD's defense metric is PPA *allowed* — lower is better defense — while SmartSim's `defense_rating` must be defensive *strength*, higher is better). Each game was simulated **300 times** with different seeds and the mean home/away score taken as SmartSim's point projection (a single seed is too stochastic to serve as a point estimate; this Monte-Carlo-mean approach is the standard way to extract one from a stochastic simulator).
- **Disclosed limitation, applies evenly to both non-market systems**: both the current engine's stored predictions (final snapshot, taken after the season) and SmartSim's PPA-based ratings (season-long aggregates) use information that would not have been available walk-forward, in-season. This is a mild lookahead bias but it affects the current engine and SmartSim equally, so it does not favor one over the other in this comparison — it only means neither's numbers here represent true blind, pre-game accuracy.
- **Not yet exercised**: SmartSim's own market-facing feature-generation payload (`feature_generation_payload`) beyond the four rating fields — no market-derived priors, no injury/weather/pace context. This is the simplest possible fair-ish feed, not a tuned integration.

## Results

### Margin (home score − away score), N=103

| System | MAE | Bias | Correlation w/ actual |
| --- | --- | --- | --- |
| Market | **10.99** | +1.24 | **0.632** |
| Current Engine | 14.18 | −3.58 | 0.356 |
| SmartSim | 13.86 | +0.53 | **0.545** |

### Total (home + away score), N=103

| System | MAE | Bias | Correlation w/ actual |
| --- | --- | --- | --- |
| Market | **12.77** | +0.62 | **0.397** |
| Current Engine | 14.48 | −2.33 | 0.046 |
| SmartSim | 14.67 | **+6.11** | 0.358 |

### Winner-pick / against-the-spread accuracy, N=103

| System | Straight-up winner | Against the market spread |
| --- | --- | --- |
| Market | 73.8% | — |
| Current Engine | 68.0% | 55.4% |
| SmartSim | 63.1% | 50.5% |

### Cross-system independence (correlation between two systems' own predictions, not vs. actual)

| Pair | Margin | Total |
| --- | --- | --- |
| SmartSim vs. Current Engine | **0.252** | **0.092** |
| SmartSim vs. Market | 0.770 | 0.605 |
| Current Engine vs. Market | 0.395 | — |

### Per-week stability (same pattern holds in both weeks independently)

| | Week 5 (n=51) margin corr | Week 10 (n=52) margin corr | Week 5 total corr | Week 10 total corr |
| --- | --- | --- | --- | --- |
| Market | 0.723 | 0.550 | 0.443 | 0.363 |
| Current Engine | 0.428 | 0.301 | 0.076 | 0.020 |
| SmartSim | 0.660 | 0.442 | 0.356 | 0.359 |

## Concrete Examples

**Shootouts the current engine badly under-called, SmartSim tracked much closer:**

| Game | Actual total | Engine | SmartSim | Market |
| --- | --- | --- | --- | --- |
| Georgia Tech @ NC State | 84 | 37.5 (err 46.5) | 62.5 (err 21.5) | 58.5 |
| Utah State @ Vanderbilt | 90 | 47.0 (err 43.0) | 66.4 (err 23.6) | 57.8 |
| Mississippi State @ Arkansas | 73 | 42.0 (err 31.0) | 63.6 (err 9.4) | 66.5 |

**Defensive slugfests where SmartSim's high-scoring bias hurt it and the engine's low-scoring bias happened to help:**

| Game | Actual total | Engine | SmartSim | Market |
| --- | --- | --- | --- | --- |
| Kentucky @ Auburn | 13 | 35.8 (err 22.8) | 56.3 (err 43.3) | 44.5 |
| UCLA @ Northwestern | 31 | 38.9 (err 7.9) | 57.8 (err 26.8) | 46.0 |

**Games where the current engine picked the wrong side outright and SmartSim (like the market) leaned correctly:**

| Game | Actual margin | Engine | SmartSim | Market |
| --- | --- | --- | --- | --- |
| Oklahoma State @ Kansas | Kansas +17 | Oklahoma St +30.5 (wrong side) | Kansas +3.7 (right side) | Kansas +24.7 |
| Sam Houston @ Louisiana Tech | Sam Houston +41 | Louisiana Tech +20.6 (wrong side) | Sam Houston +4.4 (right side) | Sam Houston +16.5 |
| Jacksonville State @ Southern Miss | Jax St +17 | Southern Miss +20.7 (wrong side) | Jax St +1.4 (right side) | Jax St +4.8 |

## Explicit Answers

### Does SmartSim outperform current projections?

**Mixed, metric-dependent — not a clean win either way.** On correlation with actual outcomes (arguably the more important property for a *model*, since a systematic bias is a one-line recalibration but a lack of correlation isn't fixable without new signal), SmartSim clearly beats the current engine on both margin (0.545 vs 0.356) and total (0.358 vs. an almost-zero 0.046), and this holds independently in both test weeks. On margin MAE, SmartSim is essentially tied with the engine (13.86 vs 14.18) and carries far less systematic bias (+0.53 vs −3.58 — the engine has a real, structural tendency to underrate home teams). On total MAE, SmartSim is slightly worse than the engine (14.67 vs 14.48) *because of* a real, consistent +6.1-point over-projection bias. On the discrete, arguably most decision-relevant metrics — straight-up winner accuracy and against-the-spread accuracy — the current engine modestly beats SmartSim (68.0% vs 63.1%; 55.4% vs 50.5%). Neither system beats the market on any metric.

### Does SmartSim add independent signal?

**Yes, and this is the clearest finding in this assessment.** SmartSim's predictions correlate weakly with the current engine's own predictions (0.252 on margin, 0.092 on total) — far weaker than either system's correlation with the market (0.395-0.77). A system producing genuinely new information should look like this: different from the incumbent, while still tracking real-world outcomes and the market's own view reasonably well (SmartSim vs. market correlation is 0.605-0.77, higher than the current engine's own correlation with the market). The shootout/slugfest examples above show *why* the signal differs: SmartSim's explosive-play modeling picks up shootout total-scoring variance the current engine's pipeline apparently does not capture at all (total correlation 0.046 — indistinguishable from noise).

### Which outputs are most valuable?

**Margin/spread**, not total. SmartSim's margin correlation (0.545) is the strongest result in this report short of the market itself, and it is the metric where SmartSim most clearly improves on the current engine's demonstrated weakness (wrong-side picks on Oklahoma State/Kansas, Sam Houston/Louisiana Tech, Jacksonville State/Southern Miss — all games the engine called for the loser). Total is the weaker output today: real signal is present (0.358 correlation, nearly matching the market's 0.397), but it is undermined by a consistent, uncorrected +6-point over-projection bias that was never surfaced or tuned before — because every prior SmartSim calibration and validation pass (`ncaaf_profile_validation_report.md`, `ncaaf_week1_shakeout_report.md`) used **neutral (0.0/0.0) team ratings**, never real, non-neutral inputs. This is a newly-discovered, easily-named gap: the profile's yardage/scoring levers have only ever been measured with both teams rated identically; feeding real, differentiated ratings is untested territory, and the bias found here is the first evidence of what that territory looks like.

### Primary, secondary, or validation layer?

**Secondary signal, not primary, and not (yet) a pure validation layer.** Three reasons: (1) SmartSim does not beat the current engine outright — it wins on correlation/bias, loses on discrete pick accuracy, so replacing the engine wholesale would trade one set of errors for a different, not obviously smaller, set. (2) The independence finding is the real prize here — SmartSim's low correlation with the current engine (0.252 margin / 0.092 total) means an ensemble or a "flag when SmartSim and the engine disagree sharply" layer would very likely outperform either system alone, which is the classic profile of a valuable *secondary* signal, not a replacement. (3) It is not purely a validation layer either, because a validation layer implies SmartSim mostly agrees with and double-checks the engine — the data shows the opposite, that they diverge; that divergence is a feature (independent information) for a secondary-signal role, but would be a liability for a validation role where the point is to confirm the primary system rather than contradict it.

**Concrete next step, not executed here (would require touching SmartSim, out of scope for this assessment):** correct the discovered total-scoring bias — even a flat recalibration (e.g., a per-league additive/multiplicative adjustment learned from exactly this kind of real-rating backtest, or extending the `CalibrationProfile` seam with rating-response levers analogous to the red-zone fields added in v2) — before total is worth surfacing to users; margin/spread is closer to usable today as a secondary signal.

## Deliverables

- This report.
- No SmartSim 2.0 code touched (per constraint); all analysis lives in a disposable script, not committed (matches the project's established tmp-file convention, gitignored).
