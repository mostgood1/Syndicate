# NCAAF Coaching Continuity Onboarding Report

## Purpose

This report defines the source requirements, artifact design, and implementation path for NCAAF coaching continuity onboarding.

It is a planning and contract document only.

Scope constraints:

- No football model changes.
- No roster implementation.
- No transfer implementation.
- No returning-production implementation.
- No recruiting implementation.
- No NFL onboarding artifact changes.

## Current State

NCAAF onboarding now has completed layers for schedule, team metadata, team registry, player identity, roster snapshot, transfer portal, and returning production.

Coaching continuity is the next missing layer.

The repository contains planning references to coaching continuity, but there is no visible canonical coaching-continuity artifact and no implemented builder for it.

## Coaching Data Surface Audit

### CFBD docs surface

The live CFBD docs expose a generic `/coaches` endpoint under the coaches category.

Observed documentation surface:

- `GET /coaches`

What is not visible in the docs surface we inspected:

- no explicit head-coach continuity snapshot contract
- no explicit offensive coordinator continuity contract
- no explicit defensive coordinator continuity contract
- no explicit season-over-season coaching continuity artifact contract
- no explicit staff-history artifact surfaced in the docs excerpt

### Repository surface

Repository search shows planning references only.

Visible planning statements:

- coaching continuity is currently listed as a missing repo-surface layer
- M6 is described as requiring head-coach and staff continuity, scheme continuity, or equivalent program-level stability signals
- the team registry spec already anticipates coaching-continuity joins

What is not visible:

- no `ncaaf_coaching_continuity_snapshot.csv`
- no coaching continuity generation report
- no coaching continuity builder script
- no validated coaching continuity test slice

## Available Coaching Information

Based on the current evidence, the following coaching information may be available from current sources:

- a generic coach data endpoint from CFBD
- team/program identity from the canonical team registry
- season context from the existing NCAAF artifact chain

The following coaching information is not yet proven available from the current source surfaces in a canonical, season-dated way:

- head coach by season
- offensive coordinator by season
- defensive coordinator by season
- coaching changes between seasons
- staff continuity across seasons
- scheme continuity across seasons

## What Current Sources Can Support

Existing sources can support a partial coaching continuity model if CFBD `/coaches` contains usable season-dated coach rows.

At minimum, the existing source stack can likely support:

- team-level program identity joins through the registry
- season alignment through the current NCAAF artifact chain
- downstream joins to roster, transfer, and returning-production context

However, existing sources have not yet been shown to provide a complete coaching continuity layer on their own.

## What Requires a New Source or New Derived Artifact

The following likely require a new source interpretation, a new derived artifact, or both:

- season-over-season head coach continuity
- offensive coordinator continuity
- defensive coordinator continuity
- staff turnover tracking
- scheme continuity scoring
- canonical change detection between seasons

If CFBD `/coaches` only exposes raw coach records, then coaching continuity must be derived locally from those records plus team registry joins.

If `/coaches` does not expose enough season metadata or role metadata, then a new source would be required for a complete continuity artifact.

## Recommended Canonical Artifact

The canonical artifact should be a season-dated coaching continuity snapshot CSV.

### Required filename

- `ncaaf_coaching_continuity_snapshot.csv`

### Recommended location

- `data/ncaaf_source/source_artifacts/data/processed/coaching_continuity/`

### Why this artifact

- it matches the existing NCAAF source-artifact pattern
- it gives downstream layers a stable program-stability signal
- it can be joined to team registry, roster, transfer, and returning-production artifacts
- it preserves season-over-season coaching changes as a first-class input

## Required Fields

The canonical coaching continuity snapshot must include the following required fields on every row:

- `team_id`
- `team_name`
- `conference`
- `season`
- `head_coach`
- `offensive_coordinator`
- `defensive_coordinator`
- `head_coach_changed`
- `offensive_coordinator_changed`
- `defensive_coordinator_changed`
- `coaching_continuity_score`
- `scheme_continuity_score`
- `source_system`
- `source_snapshot_date`

### Field definitions

#### `team_id`

Canonical team identifier resolved through the team registry.

#### `team_name`

Canonical team display name for the season.

#### `conference`

Season-specific conference context.

#### `season`

The season being onboarded.

#### `head_coach`

Canonical head coach name for the season.

#### `offensive_coordinator`

Canonical offensive coordinator name for the season.

#### `defensive_coordinator`

Canonical defensive coordinator name for the season.

#### `head_coach_changed`

Boolean or normalized indicator of whether the head coach changed from the prior season.

#### `offensive_coordinator_changed`

Boolean or normalized indicator of whether the offensive coordinator changed from the prior season.

#### `defensive_coordinator_changed`

Boolean or normalized indicator of whether the defensive coordinator changed from the prior season.

#### `coaching_continuity_score`

Composite continuity measure derived from coach retention and staff stability.

#### `scheme_continuity_score`

Derived scheme-stability proxy.

#### `source_system`

Provenance label for the acquisition source.

Required value:

- `cfbd`

#### `source_snapshot_date`

The date the snapshot was sourced or published.

## Optional Derived Fields

The following fields are optional for the first canonical coaching continuity version but are strongly recommended for future layers:

- `head_coach_tenure_years`
- `offensive_coordinator_tenure_years`
- `defensive_coordinator_tenure_years`
- `coaching_change_count`
- `staff_turnover_count`
- `scheme_label`
- `prior_season_head_coach`
- `prior_season_offensive_coordinator`
- `prior_season_defensive_coordinator`
- `source_row_index`
- `source_payload_hash`

These fields would help with auditability, continuity scoring, and change detection.

## Join Requirements

### Join to team registry

Every coaching continuity row must resolve to exactly one canonical team registry row.

Required behavior:

- normalize school or program naming variants to `team_id`
- preserve canonical team identity after matching
- fail validation when the team cannot be resolved uniquely

### Join to roster snapshot

The roster snapshot is not the source of coaching information, but it is a downstream continuity anchor.

Required behavior:

- allow future player-level analyses to join team coaching stability to roster composition
- support season-aligned team context for roster-based continuity analysis

### Join to transfer portal snapshot

The transfer portal snapshot is not a coaching source, but it is a useful continuity-context signal.

Required behavior:

- allow downstream analysis of how staff continuity interacts with transfer churn
- preserve season alignment for continuity comparison

### Join to returning-production snapshot

The returning-production snapshot is a natural companion signal for coaching continuity.

Required behavior:

- allow comparison of coaching stability and production retention at the team level
- support downstream evaluation of how coaching changes correlate with continuity outcomes

## Validation Requirements

The canonical coaching continuity snapshot must pass the following checks before publication:

### Structural checks

- the artifact exists as a dedicated snapshot file
- every row contains the required fields
- the file is parseable as CSV or JSON according to the implementation contract

### Identity checks

- every `team_id` resolves to the canonical team registry
- `team_name` is present for every row
- `conference` is present for every row
- `season` is present and parseable for every row

### Continuity checks

- head coach, offensive coordinator, and defensive coordinator fields are season-dated
- change indicators are consistent with prior-season comparisons
- continuity scores are stable and reproducible

### Provenance checks

- `source_system` is recorded
- `source_snapshot_date` is recorded
- source coach rows or source coach records can be traced back to the upstream feed

## What Remaining Blockers Exist?

The blockers for M6 are:

- no confirmed canonical coaching source extraction path yet
- no proven season-dated coach-role feed in the current repo surface
- no implemented coaching continuity builder
- no validated continuity scoring contract
- possible need for a new derived or source layer if CFBD `/coaches` is insufficient

## Can Existing Sources Support Coaching Continuity?

Partially, but not yet completely.

Existing sources can support coaching continuity only if CFBD `/coaches` exposes enough season-dated role records to derive head coach, offensive coordinator, and defensive coordinator continuity.

The current repo evidence does not yet prove that those role-specific, season-over-season inputs are available in a canonical form.

## What Artifact Must Exist for M6 Completion?

The canonical NCAAF coaching continuity snapshot CSV must exist, recommended as `ncaaf_coaching_continuity_snapshot.csv` under the NCAAF source artifact tree.

## What Fields Are Required?

At minimum, the snapshot needs:

- `team_id`
- `team_name`
- `conference`
- `season`
- `head_coach`
- `offensive_coordinator`
- `defensive_coordinator`
- `head_coach_changed`
- `offensive_coordinator_changed`
- `defensive_coordinator_changed`
- `coaching_continuity_score`
- `scheme_continuity_score`
- `source_system`
- `source_snapshot_date`

## Final Recommendation

Proceed with a canonical `ncaaf_coaching_continuity_snapshot.csv` design, but treat M6 as source-discovery incomplete until the coaching feed is proven to provide season-dated coach-role rows or a dedicated derived source is added.
