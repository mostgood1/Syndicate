# SmartSim 2.0 Truth Layer Plan

- Date: 2026-07-15
- Status: NFL truth layer implemented and measured (frozen as Production Candidate); **NCAAF truth layer implemented and measured**
- Architecture constraint honored: one shared **SmartSim Football Core**; league differences live in calibration profiles, not separate simulators

## Architecture

```
                SmartSim Football Core
        (play/drive/game engines, urgency states,
         situation model, calibration evaluator)
                        |
        +---------------+---------------+
        |                               |
  NFL Calibration Profile        NCAAF Calibration Profile
        |                               |
  NFL Truth Snapshot              NCAAF Truth Snapshot
  (nflverse PBP 2023-2025,        (CFBD drives + plays,
   historical_truth/)              same contract)
```

- The truth layer produces `HistoricalTruthSnapshot` objects that adapt into the existing `CalibrationBenchmarkSnapshot` via `to_calibration_snapshot()`. The evaluator, drive engine, play engine, and game loop are untouched.
- A "calibration profile" is a benchmark snapshot + league parameter set (quarter length, clock rules, OT format, prior scales). No league-specific simulator code paths beyond parameterization.

## Phase 1 — NFL Truth Layer (complete)

- `historical_truth/nfl_historical_loader.py`: season-cached nflverse PBP acquisition (2023-2025; `nfl_data_py` preferred, direct release download fallback). Cache: `data/nfl_source/historical_truth/`.
- `historical_truth/historical_snapshot_contract.py`: drive/game/metrics/snapshot contracts + calibration adapter.
- `historical_truth/historical_snapshot_builder.py`: 17,677 real drives, 816 games; seven-outcome canonical drive results; measured red-zone entry/conversion; quarter scoring from score progression.
- Findings and revised targets: see `nfl_historical_truth_report.md`.

## Phase 2 — NFL Calibration Iteration 7 (next)

1. Add a truth-backed entry point beside the proxy path (e.g., `load_truth_audit_result()`) that feeds `evaluate_simulator` with the adapted truth snapshot; keep the proxy builder as a fallback for replay compatibility.
2. Recalibrate against real targets: turnovers up to ~11.1%, made FGs up to ~15.7%, punts down to ~35.1%, plays/drive toward 5.93, Q2 scoring toward 13.91.
3. Fix the evaluator punt-yards crediting defect so drive yards is measurable (real target 30.66).
4. Split seasons into calibration (2023-2024) and holdout (2025) using the existing `CalibrationSplit` enum.

## Phase 3 — NCAAF Truth Layer (complete)

- `historical_truth/ncaaf_historical_loader.py`: CFBD acquisition (`/games`, `/drives` whole-season; `/plays` per-week, CFBD requires `week`), FBS-vs-FBS filtering, `driveResult` -> shared canonical-vocabulary mapping, and `canonicalize_ncaaf_frame()` producing the same pbp-shaped frame the NFL builder consumes. Cache: `data/ncaaf_source/historical_truth/`.
- `historical_snapshot_builder.py`: one additive change (`league: str = "nfl"` keyword, default preserves every existing call site) so the same builder now serves both leagues.
- 53,548 real drives, 2,264 games (2023-2025 regular season, FBS-vs-FBS only, ~3x the NFL sample as anticipated). Findings, full metric comparison, and explicit answers: see `ncaaf_historical_truth_report.md`.
- Headline result: punt rate, red-zone conversion, seconds/drive, plays/drive, and turnover rate are all within 3% relative of the NFL truth snapshot — evidence these are sport-invariant Football Core behaviors, not NFL-specific ones. Yards/drive (+38.6%), made-FG rate (-36.3%), and turnover-on-downs rate (+25.9%) are the metrics that must get NCAAF-specific calibration parameters.
- Tests: `tests/test_ncaaf_historical_loader.py` (6 tests), full NFL/SmartSim2 suite re-run alongside with no new failures.

## Phase 3 (original) — NCAAF Truth Layer Requirements

### Data source: CollegeFootballData (CFBD) API — key already provisioned in NCAAFCompare (`CFBD_API_KEY`)

**CFBD `/drives` (required, minimum viable):**

| Field | Truth-layer use |
| --- | --- |
| `offense`, `defense`, `game_id` | drive identity |
| `start_yardline`/`start_yards_to_goal` | field position start (maps to `start_yardline_100`) |
| `end_yardline`/`end_yards_to_goal` | field position end, red-zone entry |
| `plays`, `yards` | plays/drive, yards/drive |
| `start_time`/`end_time` (period + clock) | seconds/drive, quarter attribution |
| `drive_result` | canonical outcome mapping (TD/FG/MISSED FG/PUNT/INT/FUMBLE/DOWNS/END OF HALF/...) |
| `scoring` | scoring-drive flag |

**CFBD `/plays` (required for situational/clock calibration):**

| Field | Truth-layer use |
| --- | --- |
| `down`, `distance`, `yards_to_goal` | series conversion, third/fourth-down behavior, goal-to-go |
| `period`, `clock` | urgency-state validation, two-minute behavior, clock consumption |
| `play_type` | punt/FG/kneel/spike identification, play-calling mix |
| `offense_score`, `defense_score` | trailing/leading urgency contexts |

**CFBD `/games`:** final and quarter scores (`home_line_scores`) for game records.

### Acquisition scope

- Seasons 2023-2025, FBS regular season (~2,400 games, ~55,000 drives — 3x the NFL sample).
- Mirror to `data/ncaaf_source/historical_truth/` as season-partitioned csv.gz, same cache pattern as NFL.
- Rate limits: CFBD free tier ~1,000 calls/month; drives and plays endpoints accept season-week batching (`/drives?year=&week=`); a full 3-season mirror is ~150 calls (weeks x endpoints), comfortably within budget if cached once.

### Builder requirements (NCAAF-specific handling)

1. `ncaaf_historical_loader.py` — CFBD client with local cache; reuse the loader pattern (cached-or-fetch per season/week).
2. `drive_result` mapping into the same nine canonical results (CFBD uses variants like "INT TD", "FUMBLE RETURN TD" → turnover; "DOWNS" → turnover_on_downs; "END OF HALF"/"END OF GAME" → end_of_half).
3. Clock semantics: CFBD drive times are period-relative; convert to seconds like the NFL builder.
4. NCAAF structural parameters for the calibration profile (not the simulator): higher possessions/game (~24-26), higher totals (~55-60), wider team-quality variance, different OT format (no game clock), and the 2024+ first-down clock rule change (pre-2024 seasons differ measurably — keep per-season metrics like the NFL builder already does).
5. FBS-vs-FCS filtering: exclude games with non-FBS opponents from calibration (quality skew), or tag them in metadata.

### Deliverables

- `historical_truth/ncaaf_historical_loader.py`
- NCAAF truth snapshot via the **same** `historical_snapshot_builder`/contract (the builder takes canonicalized frames; only the loader and result mapping are league-specific)
- `ncaaf_historical_truth_report.md` — real NCAAF benchmark vs NFL benchmark vs simulator-under-NCAAF-profile
- NCAAF calibration profile: truth snapshot + structural parameter set consumed by the shared Football Core

## Phase 4 — Ongoing

- Refresh cadence: re-pull current season weekly in-season (append-only cache); prior seasons are immutable.
- Promote truth snapshots into the Syndicate artifact manifest so calibration inputs are traceable like all other Syndicate artifacts.
- Retire proxy benchmark once Iteration 7 validates parity of the pipeline (keep code for replay of historical reports).

## Guardrails

- Do not fork the simulator per league; all league behavior differences must be expressible as calibration-profile parameters or urgency/situation configuration.
- Truth snapshots are immutable, versioned inputs; calibration reports must cite snapshot source, seasons, and sample sizes.
- Every future calibration report compares against truth metrics, never proxy rows.
