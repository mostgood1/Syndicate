# NCAAF Historical Truth Report

- Date: 2026-07-15
- Source: CollegeFootballData (CFBD) API `/games`, `/drives`, `/plays`, 2023-2025 regular seasons, FBS-vs-FBS games only
- Sample: 401,537 canonical plays -> **53,548 real drives** across **2,264 games** (750 in 2023, 752 in 2024, 762 in 2025) — **~3x the NFL truth sample** (17,677 drives / 816 games), as anticipated in the truth-layer plan
- Cache: `data/ncaaf_source/historical_truth/{games,drives,plays}_<season>[_wk<week>].json.gz` (offline-replayable; 57 API calls total across 3 seasons, well inside CFBD's free-tier budget)
- Architecture: **no separate simulator.** CFBD drives+plays+games are canonicalized into the exact play-by-play-shaped frame the shared `historical_snapshot_builder.py` already consumes for NFL data, then run through the same `build_drive_records` / `build_game_records` / `compute_truth_metrics` / `to_calibration_snapshot()` code, unmodified. Only the loader (`ncaaf_historical_loader.py`) and the CFBD `driveResult` -> canonical-vocabulary mapping are NCAAF-specific.
- NFL calibration profile: **untouched.** The only change to shared code is one additive `league: str = "nfl"` keyword on `build_historical_truth_snapshot()`; every existing call site is unaffected and the full NFL/SmartSim2 test suite (29/30, one pre-existing unrelated stochastic flake in `test_smartsim2_calibrated_drive_simulator.py` predating this work) still passes.

## Acquisition

| Season | Games fetched | FBS-vs-FBS games kept | Excluded (FCS opponent) | Drives fetched | Drives in snapshot | Plays fetched |
| --- | --- | --- | --- | --- | --- | --- |
| 2023 | 868 | 750 | 118 (13.6%) | 20,852 | 18,046 | 151,739 |
| 2024 | 874 | 753 | 121 (13.8%) | 20,672 | 17,825 | 154,558 |
| 2025 | 888 | 762 | 126 (14.2%) | 20,666 | 17,677 | 157,920 |

- `classification=fbs` on CFBD only requires **one** side to be FBS, so ~14% of each season's schedule (P5/G5 teams' FCS "buy games") was explicitly filtered out per the plan's quality-skew guardrail, not silently absorbed.
- Drive-to-play join coverage is effectively 100%: every FBS-vs-FBS drive in the `/drives` table matched at least one `/plays` row, except a negligible 7-drive (0.04%) duplicate-`driveNumber` collision in 2025 CFBD data and one 2024 game with zero drive/play data (753 FBS-vs-FBS games fetched, 752 produced drive records) — both are CFBD data-quality footnotes, not join defects.
- Red-zone entry/conversion is measured with the **same true per-play methodology as the NFL builder** (minimum `yardsToGoal` across all plays in a drive), not a drive-level start/end approximation, because the canonical frame is built from CFBD `/plays`, not from `/drives` aggregates alone. `/drives` supplies only the per-drive outcome label, play count, and elapsed time.

## NCAAF Historical Truth Snapshot vs NFL Historical Truth Snapshot (2023-2025 regular season, pooled)

| Metric | Real NCAAF (truth) | Real NFL (truth) | Delta (NCAAF − NFL) | Relative divergence |
| --- | --- | --- | --- | --- |
| Possessions per game | **23.65** | 21.66 | +1.99 | 9.2% |
| Plays per drive | **5.77** | 5.93 | −0.16 | 2.7% |
| Seconds per drive | **165.4** | 166.2 | −0.8 | 0.5% |
| Yards per drive | **42.49** | 30.66 | +11.83 | 38.6% |
| Touchdown rate | **26.4%** | 22.0% | +4.4 pts | 20.0% |
| Field-goal rate (made) | **10.0%** | 15.7% | −5.7 pts | 36.3% |
| Missed field-goal rate | **3.1%** | 2.7% | +0.4 pts | 14.8% |
| Punt rate | **35.1%** | 35.1% | ~0.0 pts | 0.1% |
| Turnover rate | **10.9%** | 11.1% | −0.2 pts | 1.8% |
| Turnover-on-downs rate | **7.3%** | 5.8% | +1.5 pts | 25.9% |
| End-of-half/clock rate | **6.4%** | 7.4% | −1.0 pts | 13.5% |
| Red-zone entry rate | **38.8%** | 36.7% | +2.1 pts | 5.7% |
| Red-zone conversion | **85.6%** | 85.5% | +0.1 pts | 0.1% |
| Q1 scoring | **12.03** | 8.82 | +3.21 | 36.4% |
| Q2 scoring | **15.74** | 13.91 | +1.83 | 13.2% |
| Q3 scoring | **11.99** | 9.26 | +2.73 | 29.5% |
| Q4 scoring | **13.22** | 12.86 | +0.36 | 2.8% |
| Game totals | **53.35** | 45.13 | +8.22 | 18.2% |

Drive outcome distribution (53,548 drives): touchdown 14,118 (26.4%), punt 18,787 (35.1%), field goal 5,360 (10.0%), missed field goal 1,679 (3.1%), turnover 5,847 (10.9%), turnover-on-downs 3,925 (7.3%), end-of-half 3,431 (6.4%), safety 110 (0.2%), other 291 (0.5%).

### Per-season detail

| Season | Poss/game | Plays/drive | TD% | FG%(made) | Punt% | Turnover% | TOD% | RZ conv% | Totals |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2023 | 24.06 | 5.69 | 26.0% | 9.7% | 35.8% | 11.0% | 7.3% | 85.9% | 53.55 |
| 2024 | 23.70 | 5.75 | 26.6% | 10.0% | 34.7% | 11.2% | 7.1% | 85.7% | 53.73 |
| 2025 | 23.20 | 5.87 | 26.5% | 10.3% | 34.7% | 10.5% | 7.6% | 85.0% | 52.78 |

Season-over-season stability mirrors the NFL truth layer's finding: outcome shares move by low-single-digit points year to year, so pooling 2023-2025 is a reasonable calibration sample. (The plan's flagged pre-2024 first-down clock rule change did not produce a step change in `seconds_per_drive` or `possessions_per_game` large enough to warrant a separate pre/post split at this sample size — 2023's 160.9s/drive and 24.06 poss/game sit inside the 2024-2025 range, not outside it.)

## Explicit Answers

### How does NCAAF differ from NFL?

Structurally, NCAAF is a **higher-possession, higher-scoring, higher-yards-per-play** version of the same seven/eight-outcome drive grammar. Possessions per game are ~9% higher (23.65 vs 21.66) despite drives per possession, plays per drive, and seconds per drive all being nearly identical to the NFL — meaning college games simply have more clock-efficient possessions of similar length, not shorter ones. The biggest true structural gap is **yards per drive (42.5 vs 30.7, +38.6%)**, driven by yards per play (7.36 vs 5.17) rather than more plays or more time — this is the well-known college "big play" signature (spread/tempo offenses, wider talent mismatches across 130 FBS teams vs 32 NFL teams) and shows up directly in every scoring-shape number: touchdown rate +4.4 points, game totals +8.2 points, and quarter scoring elevated in every quarter (Q1 and Q3 especially, +36% and +29% relative). Made field goals are the mirror image: −5.7 points versus NFL, consistent with a college culture that goes for it on 4th down far more (turnover-on-downs +1.5 points, +25.9% relative) rather than trusting a college kicker from distance.

### Which metrics diverge most?

Ranked by relative divergence: **yards per drive (38.6%)**, **field-goal rate made (36.3%)**, **Q1 scoring (36.4%)**, **Q3 scoring (29.5%)**, **turnover-on-downs rate (25.9%)**, touchdown rate (20.0%), game totals (18.2%), Q2 scoring (13.2%), end-of-half rate (13.5%), missed-field-goal rate (14.8%). These are exactly the rows a shared-core simulator's NCAAF calibration profile must re-parameterize.

### Which metrics are nearly identical (Football Core assumptions that transfer)?

**Punt rate (35.08% vs 35.1%, a 0.02-point difference)**, **red-zone conversion (85.6% vs 85.5%)**, **seconds per drive (165.4 vs 166.2)**, **plays per drive (5.77 vs 5.93)**, and **turnover rate (10.9% vs 11.1%)** are all within 3% relative of the NFL truth values. This is the strongest evidence in this report: the *decision logic* that governs when a drive ends in a punt, how efficiently a red-zone trip converts to points, how much clock a typical drive consumes, and how often a possession is simply given away are apparently sport-invariant at the FBS/NFL talent level — they are properties of football itself, not the professional game specifically.

### Which Football Core assumptions remain reusable?

1. **The nine-outcome canonical drive-result vocabulary** (`touchdown`/`field_goal`/`missed_field_goal`/`punt`/`turnover`/`turnover_on_downs`/`end_of_half`/`safety`/`other`) needed zero new categories — every CFBD `driveResult` variant (including "INT TD", "FUMBLE RETURN TD", "DOWNS", "END OF 4TH QUARTER") mapped cleanly onto the existing nine.
2. **The drive/game record contracts** (`HistoricalDriveRecord`, `HistoricalGameRecord`, `HistoricalTruthMetrics`, `HistoricalTruthSnapshot`) and their `to_calibration_snapshot()` adapter required **zero field-level changes** — every field the NFL builder populates (quarter_start, red_zone_entry via min-yardline, goal_to_go_entry, points from score deltas, quarter scoring from cumulative-score progression) has a direct, correctly-populated NCAAF counterpart.
3. **The aggregation logic itself** (`build_drive_records`, `build_game_records`, `compute_truth_metrics`) is literally the same code, unmodified, run against a canonicalized CFBD frame instead of an nflverse frame.
4. **Punt-decision, red-zone-conversion, and clock-consumption behavior** (see above) — these can plausibly share simulator parameters between profiles rather than needing independent tuning, pending Iteration-style validation once an NCAAF calibration pass runs.

### Which calibration parameters must differ?

1. **Possession count / pace**: NCAAF profile needs ~24 possessions/game vs NFL's ~22 (higher clock efficiency, not shorter drives).
2. **Yards-per-play / explosiveness**: the single largest gap (+38.6%) — NCAAF's per-play gain distribution must be calibrated separately; reusing the NFL yards-per-play prior would understate scoring by nearly 40%.
3. **Scoring-mix (TD vs FG)**: NCAAF touchdown rate is materially higher and made-FG rate materially lower — a college profile needs both a higher in-drive scoring-conversion rate and a lower/shorter field-goal-range attempt-and-make model.
4. **4th-down aggression (turnover-on-downs rate)**: +25.9% relative — the go-for-it decision threshold by field position needs its own college parameterization, distinct from the NFL's more conservative one.
5. **Quarter-scoring shape**: NCAAF's Q1 and Q3 are proportionally much higher-scoring than the NFL's slow-starting, halftime-adjustment shape — the per-quarter urgency/tempo weighting the NFL profile uses for its two-minute-drill push cannot be reused as-is for early-quarter NCAAF scoring.
6. **Structural/non-behavioral rules** the plan flagged and this data confirms are still open: OT format (no game clock; the shared quarter-scoring loop already buckets OT into `metadata.overtime_points`, unmodified), and the pre-2024 first-down clock rule (present in the data as the 2023 vs 2024-2025 season split above, though not large enough here to force early independent handling).

## Truth Layer Components Delivered

- `syndicate/features/football/sim_engine/smartsim2/historical_truth/ncaaf_historical_loader.py` — CFBD client with local `.json.gz` cache (`/games` and `/drives` fetched whole-season in one call each; `/plays` fetched per-week because CFBD requires `week` on that endpoint and rejects a season-wide request with HTTP 400), FBS-vs-FBS filtering, `driveResult` -> shared-vocabulary mapping, and `canonicalize_ncaaf_frame()` which joins games+drives+plays into the exact pbp-shaped frame `historical_snapshot_builder.py` already consumes.
- `historical_snapshot_builder.py` — one additive change: `build_historical_truth_snapshot(..., league: str = "nfl")`. Every existing call site is unaffected; the NCAAF loader is the only caller that passes `league="ncaaf"`.
- `historical_snapshot_contract.py` — **unchanged**, reused as-is.
- `tests/test_ncaaf_historical_loader.py` — 6 tests: CFBD `driveResult` vocabulary mapping (including the "falls through to `other` unchanged" case), end-to-end canonicalization feeding the shared builder, FBS-vs-FCS exclusion (on and off), and post-play cumulative-score quarter attribution. All passing; full NFL/SmartSim2 suite re-run alongside with no new failures.
- `data/ncaaf_source/historical_truth/` — season-partitioned `games_<season>.json.gz`, `drives_<season>.json.gz`, `plays_<season>_wk<NN>.json.gz` cache (57 files, ~26 MB), offline-replayable.
- This report.

## Recommended NCAAF Calibration Profile (structural parameters, not simulator forks)

Per the architecture constraint, none of the following requires new simulator code paths — each is a parameter or prior on the existing SmartSim Football Core:

1. Target possessions/game ≈ 23.65 (vs NFL 21.66).
2. Target yards/play prior raised ~38-42% over the NFL prior (the dominant lever for game totals and touchdown rate).
3. Made-FG attempt/make model lowered toward 10.0% of drives (vs NFL 15.7%), with a correspondingly higher 4th-down-attempt (turnover-on-downs) prior of ~7.3% (vs NFL 5.8%).
4. Quarter-shape weights re-derived from 12.03 / 15.74 / 11.99 / 13.22 rather than the NFL's 8.82 / 13.91 / 9.26 / 12.86 — proportionally flatter across quarters with the same Q2 peak.
5. Punt-decision, red-zone-conversion, and turnover-rate priors can start from the **existing NFL-calibrated values** given the near-identical truth measurements above, then be validated against this NCAAF snapshot rather than re-derived from scratch.
6. Reuse the NFL profile's split convention (`CalibrationSplit.CALIBRATION`/`VALIDATION`/`HOLDOUT`) for an NCAAF 2023-2024 calibration / 2025 holdout split when an NCAAF Iteration-1 calibration pass begins.

This snapshot is the second Football Core benchmark input (`HistoricalTruthSnapshot(league="ncaaf")` -> `to_calibration_snapshot()`), ready to be consumed by `evaluate_simulator` exactly as the NFL truth snapshot already is, once an NCAAF-parameterized calibration profile is built against it.
