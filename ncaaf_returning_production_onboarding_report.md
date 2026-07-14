# NCAAF Returning Production Onboarding Report

## Purpose

This report defines the source requirements and artifact design for NCAAF returning-production onboarding using the completed team registry, player identity snapshot, roster snapshot, and transfer portal snapshot as the join backbone.

It is a planning and contract document only.

Scope constraints:

- No football model changes.
- No roster implementation.
- No transfer implementation.
- No recruiting implementation.
- No coaching implementation.
- No NFL onboarding artifact changes.

## Current State

CFBD supports returning production at the team level today.

The live `/player/returning` endpoint returns season-dated team records with conference context and returning-production metrics. That makes CFBD a viable source for a canonical team-level returning-production snapshot.

However, the live CFBD returning-production feed does not expose player-level returning production in the observed payload. That means player-level returning production is not a direct CFBD source surface and would have to be derived from other joins or introduced by a future source.

The roster and transfer layers now exist, so transfer-adjusted returning production can be designed as a derived layer built on top of the team-level CFBD returning-production feed plus roster and transfer joins.

## Available Data

### CFBD returning-production surface

The live CFBD API exposes `/player/returning`.

Observed row fields:

- `season`
- `team`
- `conference`
- `totalPPA`
- `totalPassingPPA`
- `totalReceivingPPA`
- `totalRushingPPA`
- `percentPPA`
- `percentPassingPPA`
- `percentReceivingPPA`
- `percentRushingPPA`
- `usage`
- `passingUsage`
- `receivingUsage`
- `rushingUsage`

Observed behavior:

- the endpoint returns one row per team for the requested season
- the feed is season-dated
- the feed includes conference context
- the feed is team-level returning production, not player-level returning production

### Canonical team registry

The NCAAF team registry is the join backbone for CFBD team labels.

Required fields:

- `team_id`
- `canonical_team_name`
- `abbreviation`
- `conference`
- `subdivision`
- `aliases`

### Player identity snapshot

The canonical NCAAF player identity snapshot exists and contains:

- `player_id`
- `player_name`
- `team_id`
- `position`
- `season`

This layer is necessary for any player-level continuity logic, even though CFBD returning production is team-level today.

### Roster snapshot

The canonical NCAAF roster snapshot exists and contains:

- `player_id`
- `player_name`
- `team_id`
- `position`
- `season`
- `roster_status`
- `source_system`
- `source_snapshot_date`

This layer is the roster anchor for season membership and continuity checks.

### Transfer portal snapshot

The canonical NCAAF transfer portal snapshot exists and contains:

- `player_id`
- `player_name`
- `origin_team_id`
- `destination_team_id`
- `transfer_date`
- `season`
- `position`
- `eligibility`
- `source_system`
- `source_snapshot_date`

This layer is required to estimate transfer-adjusted continuity.

## Missing Data

The following returning-production data is still missing from the repository surface as a dedicated artifact layer:

- a canonical NCAAF returning-production snapshot file
- a manifest pointer for returning production
- player-level returning-production rows from CFBD or another visible source
- explicit transfer-adjustment fields
- a derived continuity artifact that can be reused by later layers

### Specifically missing returning-production fields

The current CFBD surface does not visibly provide a dedicated dataset with all of the following on a player-level row:

- `player_id`
- `player_name`
- `team_id`
- `position`
- `season`
- `returning_production`
- `returning_usage`

### What CFBD does and does not provide

CFBD does provide:

- team-level returning production
- conference context
- season context

CFBD does not provide, in the observed payload:

- player-level returning production rows
- explicit player identifiers in the returning-production feed
- direct transfer-adjusted returning production

## Join Requirements

### Join to canonical team registry

Every returning-production row must resolve to exactly one canonical team registry row.

Required behavior:

- normalize the CFBD team label to `team_id`
- preserve canonical team identity after matching
- fail validation when the team cannot be resolved uniquely

### Join to roster snapshot

For transfer-adjusted returning production, the team-level row must be connected to the current roster snapshot.

Required behavior:

- roster rows define which players are present for the season cut
- roster status should determine whether a player is counted as returning or not
- the roster snapshot must be the local source of truth for player continuity joins

### Join to transfer portal snapshot

For transfer-adjusted returning production, the team-level row must be adjusted using transfer movements.

Required behavior:

- incoming transfers should not be counted as returning production
- outgoing transfers should reduce returning continuity when they materially change the roster
- portal rows must be tied back to the current team and season through the transfer snapshot

### Join to player identity snapshot

If a player-level returning-production artifact is added later, it must resolve through the identity snapshot first.

Required behavior:

- `player_id` is the preferred join key
- `player_name` is the fallback matching key
- `team_id` and `season` must match the identity backbone

## Artifact Design

### Canonical artifact

The required artifact for the first returning-production layer should be a canonical team-level NCAAF returning-production snapshot CSV.

### Recommended filename

- `ncaaf_returning_production_snapshot.csv`

### Recommended location

- `data/ncaaf_source/source_artifacts/data/processed/returning_production/`

### Why this design

- CFBD currently exposes team-level returning production directly
- the artifact can be generated without a new model change
- the artifact can serve as the source of truth for later transfer-adjusted or player-derived layers

## Required Fields

The canonical NCAAF returning-production snapshot must include the following required fields on every row:

- `team_id`
- `team_name`
- `conference`
- `season`
- `total_ppa`
- `total_passing_ppa`
- `total_receiving_ppa`
- `total_rushing_ppa`
- `percent_ppa`
- `percent_passing_ppa`
- `percent_receiving_ppa`
- `percent_rushing_ppa`
- `usage`
- `passing_usage`
- `receiving_usage`
- `rushing_usage`
- `source_system`
- `source_snapshot_date`

### Required field definitions

#### `team_id`

Canonical team identifier resolved through the NCAAF team registry.

#### `team_name`

Canonical team display name for the season.

#### `conference`

Season-specific conference context from CFBD or the team registry.

#### `season`

Season for the returning-production snapshot.

#### PPA and usage fields

These fields represent the team-level returning-production metrics returned by CFBD.

#### `source_system`

Provenance label for the acquisition source.

Required value:

- `cfbd`

#### `source_snapshot_date`

Date or date-like value when the snapshot was sourced or published.

## Optional Fields

The following fields are optional for the first canonical returning-production version but are strongly recommended for future layers:

- `team_abbreviation`
- `subdivision`
- `source_team_name`
- `source_conference`
- `source_row_index`
- `source_payload_hash`
- `transfer_adjusted_ppa`
- `transfer_adjusted_usage`
- `returning_player_count`
- `transferred_out_player_count`
- `incoming_transfer_count`

### Optional field guidance

These fields are useful for transfer-adjusted continuity, auditability, and future player-level derivations, but they are not required for the first team-level snapshot.

## Validation Requirements

The canonical returning-production snapshot must pass the following checks before publication:

### Structural checks

- the artifact exists as a dedicated snapshot file
- every row contains the required fields
- the file is parseable as CSV or JSON according to the implementation contract

### Identity checks

- every `team_id` resolves to the canonical team registry
- `team_name` is present for every row
- `conference` is present for every row or explicitly marked unknown

### Coverage checks

- the snapshot is season-dated
- the snapshot covers the intended season and team set returned by CFBD
- duplicate team rows are handled deterministically

### Transfer-adjustment checks

- transfer-adjusted metrics can be derived from roster and transfer joins
- incoming and outgoing transfer movements are visible to the adjustment layer
- transfer-adjusted values do not overwrite the base CFBD values without provenance

### Provenance checks

- source system is recorded as `cfbd`
- source snapshot date is recorded
- the base CFBD team-level values are preserved

## Risks

### Risk 1: CFBD is team-level, not player-level

The live returning-production feed is useful, but it is not player-level in the observed payload.

### Risk 2: Transfer adjustment is derived, not native

Any transfer-adjusted returning production will have to be built from local roster and transfer joins.

### Risk 3: Conference membership may drift across seasons

The returning-production artifact must stay season-dated and registry-aware.

### Risk 4: Player-level continuity may require a separate artifact later

If the product eventually needs player-level returning production, that will require a new derived layer beyond the current CFBD feed.

## M5 Readiness Assessment

M5 is not complete yet.

### What is ready

- canonical team registry exists
- canonical player identity snapshot exists
- canonical roster snapshot exists
- canonical transfer portal snapshot exists
- CFBD exposes team-level returning production

### What is not ready

- no canonical returning-production snapshot exists yet
- no transfer-adjusted returning-production artifact exists yet
- no player-level returning-production source is visible in CFBD or the repo surface

### Readiness judgment

Returning-production onboarding can begin from CFBD, but M5 cannot be formally closed until the canonical returning-production artifact is generated and the transfer-adjustment contract is published.

## Final Answers

### Can CFBD support returning production?

Yes, CFBD supports team-level returning production through `/player/returning`. The observed feed is season-dated and returns team, conference, and returning-production metrics.

### What artifact must exist?

A canonical NCAAF returning-production snapshot CSV, recommended as `ncaaf_returning_production_snapshot.csv` under the NCAAF source artifact tree.

### What fields are required?

At minimum: `team_id`, `team_name`, `conference`, `season`, the returning-production metric fields (`total_ppa`, `total_passing_ppa`, `total_receiving_ppa`, `total_rushing_ppa`, `percent_ppa`, `percent_passing_ppa`, `percent_receiving_ppa`, `percent_rushing_ppa`, `usage`, `passing_usage`, `receiving_usage`, `rushing_usage`), plus `source_system` and `source_snapshot_date`.

### What remains before M5 can be considered complete?

The repository still needs the canonical returning-production artifact itself, a publication path, validation, and a transfer-adjustment contract that uses the roster and transfer snapshots to derive continuity adjustments.
