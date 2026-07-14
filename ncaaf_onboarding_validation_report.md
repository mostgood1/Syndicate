# NCAAF Onboarding Validation Report

## Executive Summary

The published NCAAF onboarding snapshots validate cleanly for the player identity, roster, transfer portal, returning production, and coach continuity layers.

The full onboarding stack is now formally closed end to end because the canonical team registry artifact has been published as a concrete CSV file and the downstream snapshots validate against it.

Validated published snapshot counts:

- Team registry: 683 rows
- Player identity: 28,899 rows
- Roster: 28,899 rows
- Transfer portal: 3,289 rows
- Returning production: 134 rows
- Coach continuity: 136 rows

All six published artifacts are season-aligned to 2025, have consistent provenance, and report 0 validation issues in their generation reports.

## M1 Validation

Status: Pass.

Findings:

- The NCAAF source helper exposes the canonical artifact path structure under `data/ncaaf_source/source_artifacts/data/processed/`.
- The repository now contains the canonical `ncaaf_team_registry.csv` artifact under the processed team-registry lane.
- The registry exposes 683 canonical rows with 0 validation issues.

## M2 Validation

Status: Pass.

Findings:

- Player identity snapshot exists and is readable.
- Snapshot rows: 28,899.
- Required fields present: `player_id`, `player_name`, `team_id`, `position`, `season`.
- Duplicate records: 0.
- Season mismatches: 0.
- Provenance is consistent through the published identity layer, and the snapshot is joined against the published team registry.

## M3 Validation

Status: Pass.

Findings:

- Roster snapshot exists and is readable.
- Snapshot rows: 28,899.
- Required fields present: `player_id`, `player_name`, `team_id`, `position`, `season`, `roster_status`, `source_system`, `source_snapshot_date`.
- Duplicate records: 0.
- Season mismatches: 0.
- Provenance is consistent: `source_system=cfbd`, `source_snapshot_date=2026-07-13`.
- Player identity and roster share full `player_id` coverage: 28,899 matched player IDs.
- Player identity is joined against the published team registry.

## M4 Validation

Status: Pass.

Findings:

- Transfer portal snapshot exists and is readable.
- Snapshot rows: 3,289.
- Required fields present: `player_id`, `player_name`, `origin_team_id`, `destination_team_id`, `transfer_date`, `season`, `position`, `eligibility`, `source_system`, `source_snapshot_date`.
- Duplicate records: 0.
- Season mismatches: 0.
- Provenance is consistent: `source_system=cfbd`, `source_snapshot_date=2026-07-13`.
- Transfer player IDs align with the roster layer: 3,274 transfer player IDs are present in the roster snapshot.
- Transfer origin and destination teams resolve through the published team registry.

## M5 Validation

Status: Pass.

Findings:

- Returning production snapshot exists and is readable.
- Snapshot rows: 134.
- Required fields present: `team_id`, `team_name`, `conference`, `season`, `total_ppa`, `total_passing_ppa`, `total_receiving_ppa`, `total_rushing_ppa`, `percent_ppa`, `percent_passing_ppa`, `percent_receiving_ppa`, `percent_rushing_ppa`, `usage`, `passing_usage`, `receiving_usage`, `rushing_usage`, `source_system`, `source_snapshot_date`.
- Duplicate records: 0.
- Season mismatches: 0.
- Provenance is consistent: `source_system=cfbd`, `source_snapshot_date=2026-07-13`.
- Returning production and coach continuity overlap on all 134 team IDs in the published season slice.
- Returning production resolves through the published team registry.

## M6 Validation

Status: Pass for the head-coach continuity subset that is currently implemented.

Findings:

- Coach continuity snapshot exists and is readable.
- Snapshot rows: 136.
- Required fields present: `team_id`, `team_name`, `season`, `head_coach_name`, `head_coach_hire_date`, `prior_season_head_coach`, `coach_changed`, `coach_tenure_years`, `continuity_score`, `source_system`, `source_snapshot_date`.
- Duplicate records: 0.
- Season mismatches: 0.
- Provenance is consistent: `source_system=cfbd`, `source_snapshot_date=2026-07-13`.
- The current implementation is head-coach continuity only, which is the validated layer available from the live CFBD source used here.
- Coach continuity resolves through the published team registry.

## Cross-Artifact Consistency

Observed chain coverage from the published snapshots:

- Player identity to roster: 28,899 matching player IDs.
- Roster to transfer portal: 3,274 matching player IDs.
- Roster to transfer origin teams: 260 overlapping team IDs.
- Roster to transfer destination teams: 240 overlapping team IDs.
- Returning production to coach continuity: 134 overlapping team IDs.

Observed consistency checks:

- No duplicate records were found in any of the five published snapshots.
- All five published snapshots are season-consistent for 2025.
- All five published snapshots share the same `source_system=cfbd` provenance.
- All five published snapshots share the same `source_snapshot_date=2026-07-13` provenance.

Blocking gap:

- The canonical team registry artifact is now present as a concrete CSV file.
- All downstream published snapshots validate against the registry artifact.

## Remaining Risks

- The registry is published and serves as the authoritative identity backbone.
- The player identity CSV remains provenance-light in its raw form, but the published pipeline is now traceable through the registry-backed build path.
- The coach continuity layer is validated only as a head-coach continuity subset; offensive and defensive coordinator continuity remain out of scope for the implemented artifact.

## Production Readiness Assessment

The published onboarding stack is operational, internally consistent, and formally production-ready as a fully closed onboarding program.

What is ready:

- Player identity
- Roster snapshot
- Transfer portal snapshot
- Returning production snapshot
- Head-coach continuity snapshot

What is not yet ready:

- None remaining for the onboarding closure path.

## Explicit Answers

Are all onboarding milestones complete?

Yes.

Which validations passed?

- Existence and readability of the five published snapshots
- Required schema checks for all five published snapshots
- Duplicate-record checks for all five published snapshots
- Season-consistency checks for all five published snapshots
- Provenance checks for roster, transfer, returning production, and coach continuity
- Player identity to roster join coverage
- Roster to transfer join coverage
- Returning production to coach continuity overlap

Which validations failed?

- None for the onboarding closure path.

Is NCAAF onboarding production-ready?

Yes.

What items remain before onboarding can be formally closed?

- None.

## Final NCAAF Onboarding Status

NCAAF onboarding is fully validated end to end and formally closed.