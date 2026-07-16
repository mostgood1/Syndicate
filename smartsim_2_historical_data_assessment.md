# SmartSim 2.0 Historical Data Assessment

- Date: 2026-07-15
- Scope: data inventory and benchmark-quality assessment only; no simulation logic modified
- References: Iteration 4-6 calibration reports; proxy benchmark builder (`syndicate/features/football/sim_engine/smartsim2/calibration/baseline_audit.py`)

## 1. Dataset Inventory

### NFL (NFL-Betting workspace: `nfl_compare/data/`)

| Dataset | Grain | Contents |
| --- | --- | --- |
| `backtests/<season_wk>/games_details.csv` | game | actual final + quarter scores (home_q1..q4/away_q1..q4), market spread/total (open+close), EPA features, pace, pass/rush rates, weather, roof/surface, Elo; 2023 wk17, 2024 wk17/18, all 2025 weeks incl. `2025_all` |
| `pfr_drive_stats.csv` | team-week | drives, points/TD/FG per drive, avg starting field position, yards per drive, seconds per drive |
| `redzone_splits.csv` | team-week | offensive/defensive red-zone TD rate and efficiency |
| `special_teams.csv` | team-week | FG accuracy, punt EPA, kick-return EPA, touchback rate |
| `penalties_stats.csv` | team-week | penalty rate, turnover-adjusted rate |
| `explosive_rates.csv` | team-week | explosive pass rate, explosive run rate |
| `team_stats.csv` | team-week | off/def EPA (incl. half splits), pace secs/play, pass/rush rate, sack rates, RZ pass rates, QB adj, SOS |
| `external/nfl_data_py/*.parquet` | player-week | seasonal + weekly rosters (nflverse) |
| weather, odds, props, depth charts, officiating, team ratings | game/week | situational context (not currently used by SmartSim calibration) |

Key tooling fact: **`nfl_data_py` is already integrated** in NFL-Betting (`scripts/build_phase_a_features.py` imports `import_pbp_data`; roster and score updaters use it). True nflverse play-by-play is one function call away — it is simply not mirrored or used by the SmartSim benchmark.

### NCAAF (NCAAFCompare + Syndicate `data/ncaaf_source/`)

| Dataset | Grain | Contents |
| --- | --- | --- |
| `college_football_schedule_2025_predicted_totals_enhanced_*.csv` | game | schedule, predicted totals, market lines, weather, scores |
| `recommendations_*.csv/json` | game | model recommendations |

Key tooling fact: NCAAFCompare already authenticates to the **CollegeFootballData (CFBD) API** (`CFBD_API_KEY`, used in `scripts/add_postseason_games_2025.py`). CFBD exposes `/drives` and `/plays` endpoints, but neither is mirrored locally.

### Syndicate mirrors (`data/nfl_source/`, `data/ncaaf_source/`)
Odds/lines/props/artifacts only — no drive or play-by-play data.

## 2. Categorization

| Category | Available? | Source | Quality |
| --- | --- | --- | --- |
| Game-level | ✅ Yes | games_details.csv (532+ games, incl. quarter scores) | Actual results — reliable |
| Drive-level | ⚠️ Aggregates only | pfr_drive_stats.csv (team-week means, not per-drive records) | Real but lossy — no per-drive outcomes |
| Play-by-play | ❌ Not mirrored | nfl_data_py can fetch (integration exists) | Absent locally |
| Red-zone | ⚠️ Aggregates only | redzone_splits.csv (team-week TD rate/efficiency) | Real but definitionally different from per-entry conversion |
| Situational (down/distance, third down, goal-to-go) | ❌ None | — | Absent |
| Clock-management (stops, kneels, two-minute, timeouts) | ❌ None | — | Absent |
| NCAAF (all categories below game level) | ❌ None | CFBD API available but not mirrored | Absent |

## 3. Metrics With Reliable Historical Grounding

Grounded in actual game or team-week data:

- **game_totals** and **quarter scoring (Q1-Q4)** — actual scores in games_details
- **possessions_per_game** — pfr drives counts
- **drive_length_seconds** — pfr seconds_per_drive
- **drive_length_yards** — pfr yards_per_drive
- **average starting field position** — pfr avg_start_fp
- **FG accuracy / touchback rate** — special_teams
- **explosive play rates** — explosive_rates
- **red-zone TD rate (team-week aggregate)** — redzone_splits

These are the rows where Iteration 6 already sits near benchmark (totals 0.060, possessions 0.027, drive seconds 0.077, TD rate 0.047 normalized error) — the simulator converges where the data is real.

## 4. Metrics Estimated From Proxy Construction

The benchmark builder synthesizes 11,233 per-drive records from team-week aggregates. Each of these rows is an artifact of that construction, not measured football:

| Proxy metric | How it is fabricated | Consequence |
| --- | --- | --- |
| punt_rate (59.0%) | residual: drives − TDs − FGs − turnovers | absorbs missed FGs, turnover-on-downs, and clock stops that the proxy cannot represent — overstated |
| turnover_rate (0.4%) | penalties_stats `turnover_adj_rate` (a penalty-adjustment factor, not giveaways per drive) | real NFL is ~10% of drives — understated by ~25x; permanently the "largest normalized error" |
| missed_field_goal (0.000) | not representable | simulator's realistic ~2% share reads as pure error |
| turnover_on_downs (0.000) | not representable | correct desperation football reads as error |
| clock stops (0.000) | not representable | the ~9% structural floor (2 half-ending drives/game) reads as error |
| drive_length_plays (4.05) | seconds_per_drive ÷ pace_secs_play | synthetic ratio; real NFL ~5.6-6.0 plays/drive — the simulator's 6.9 is closer to reality than to the proxy |
| red_zone_conversion (43.1%) | synthetic entry flag from start_fp + yards_per_drive | real NFL score-per-trip is ~80-88%; simulator's 87% is realistic |
| drive quarter attribution | round-robin `1 + (index % 4)` | benchmark quarter mix at drive level is fictional |
| goal-to-go / situational splits | not represented at all | uncheckable against proxy |

Also note one **evaluator artifact**: punt net yards are credited to `drive_length_yards` in simulated drives, inflating that metric under a punt-heavy mix regardless of benchmark quality.

## 5. Are Existing NFL Sources Sufficient?

**No — for the next calibration stage.** The proxy is sufficient for what it already achieved (possessions, totals, quarter shape, TD rate, drive time). It cannot support the remaining frontier because the outcome-mix rows (punt/turnover/TOD/missed FG/stops), plays-per-drive, red-zone conversion, and all situational/clock behavior are either fabricated or absent. Iterations 4-6 progressively consumed the proxy's real information; what is left to tune against it is mostly noise.

## 6. What Additional NFL Data Would Improve Calibration

Priority-ordered, all obtainable through the already-integrated `nfl_data_py` (nflverse):

1. **True play-by-play, 2023-2025** (`import_pbp_data`): contains per-play down, distance, yardline, clock, quarter, play type, EPA, and drive identifiers. From this one mirror, derive:
   - true per-drive outcome table (TD / FG / missed FG / punt / turnover / TOD / end-of-half) — replaces the residual-punt and fake-turnover rows
   - true plays, seconds, yards per drive distributions (not just means)
   - true series and third-down conversion rates
   - true red-zone entry and per-entry conversion
   - true clock-stop / kneel share and two-minute scoring rates by quarter
   - situational play-calling (4th-down decision rates by field position — directly validates the Iteration 4 gates)
2. **Drive-level benchmark snapshot builder**: a new `CalibrationBenchmarkSnapshot` source that reads real drives instead of synthesizing them (additive; the proxy path can remain as fallback).
3. Optional: nflverse schedules/results for cross-validation of games_details quarter scores.

## 7. What NCAAF Historical Data Is Required

NCAAF currently has **zero** sub-game-level data, so an NCAAF SmartSim cannot be calibrated at all beyond totals. Required, in order:

1. **CFBD `/drives`** for 2023-2025 FBS seasons — per-drive start/end field position, plays, yards, seconds, and result (the direct NCAAF equivalent of the drive benchmark). API key already provisioned.
2. **CFBD `/plays`** for situational and clock behavior (down/distance, play type, clock).
3. NCAAF-specific structural parameters the NFL benchmark cannot supply: overtime format, clock-stop-on-first-down rule (pre-2024 rules differ), higher possession counts, wider team-quality spread.

## 8. Explicit Answers

- **What is the current calibration ceiling?** The proxy's real information is exhausted. Every metric grounded in actual data is at normalized error 0.014-0.096 (totals 0.060, possessions 0.027, Q1 0.014, Q4 0.074, drive seconds 0.077, TD rate 0.047). The remaining large rows — turnover_rate (22.97), punt share gap, plays/drive, red-zone conversion — cannot be improved against this benchmark without tuning the simulator toward fabricated values, i.e., making it less realistic to score better.
- **Which remaining errors are benchmark artifacts?** turnover_rate (0.4% proxy vs ~10% real), punt_rate residual inflation (59.0%), missed_field_goal = 0, turnover_on_downs = 0, clock stops = 0, drive_length_plays = 4.05 (synthetic ratio; real ~5.6-6.0), red_zone_conversion = 43.1% (real ~80-88%), and drive-level quarter attribution.
- **Which remaining errors are simulator artifacts?** (a) the Q2 halftime scoring push is still ~2 points light (11.76 vs 13.81 — real quarter scores, so this is a genuine gap); (b) `drive_length_yards` inflation from crediting punt net yards to drives is an evaluator accounting defect; (c) true giveaway rate (~6% of drives) has never been validated against real data and situational play-calling (down/distance tendencies) is uncalibrated — unknown rather than known-wrong.
- **Is true NFL PBP required?** Yes. It is the single dataset that converts five fabricated benchmark rows into measured ones, and the acquisition cost is minimal because `nfl_data_py` is already a working dependency in NFL-Betting.
- **Is true NCAAF PBP required?** Yes, for any NCAAF SmartSim calibration — nothing below game level exists locally. CFBD `/drives` is the minimum; `/plays` is needed for situational/clock work. The API integration already exists.
- **What datasets should be acquired next?** (1) nflverse PBP 2023-2025 mirrored locally (parquet, one file per season); (2) a real drive-level benchmark table derived from it; (3) CFBD drives 2023-2025 for NCAAF; (4) CFBD plays for NCAAF situational calibration.

## 9. Final Verdict

**Data Limited.**

Iteration 6 demonstrated that wherever the benchmark contains real football measurements, the simulator converges to within ~3-10% — and wherever it diverges most, the benchmark value is fabricated (residual punts, penalty-derived turnovers, zero-stop encoding, synthetic plays-per-drive). Two bounded simulator-side items remain (Q2 halftime push, punt-yardage accounting in the evaluator), but neither changes the conclusion: the next material calibration gain requires mirroring true NFL play-by-play (already one `nfl_data_py` call away) and CFBD drive data for NCAAF, then rebuilding the benchmark snapshot from real drives before any further simulator tuning.
