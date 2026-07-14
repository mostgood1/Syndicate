# NCAAF Transfer Portal Onboarding Report

## Purpose

This report defines the transfer-portal onboarding path for NCAAF using the canonical team registry, the CFBD-backed player identity snapshot, and the canonical roster snapshot as the join backbone.

It is a planning and contract document only.

Scope constraints:

- No football model changes.
- No recruiting implementation.
- No coaching implementation.
- No transfer implementation.
- No NFL onboarding artifact changes.

## Current State

The roster layer now exists, and CFBD exposes a live transfer-portal surface.

That means transfer onboarding is no longer blocked by missing team identity, missing player identity, or missing roster identity.

What remains is to define a canonical transfer portal artifact that can normalize CFBD portal rows into a season-dated transfer snapshot and join that snapshot back to the team registry, identity snapshot, and roster snapshot.

## Available Data

### CFBD transfer portal surface

The live CFBD API exposes `/player/portal`.

The returned rows include the following fields:

- `season`
- `firstName`
- `lastName`
- `position`
- `origin`
- `destination`
- `transferDate`
- `rating`
- `stars`
- `eligibility`

Observed behavior:

- the endpoint returns a live season-dated transfer list
- the feed includes origin school and destination school labels
- the feed includes transfer timing through `transferDate`
- the feed includes eligibility classification
- the feed does not expose a stable player identifier in the portal row itself

### CFBD player search surface

The live CFBD API exposes `/player/search`.

The returned rows include fields such as:

- `id`
- `team`
- `name`
- `firstName`
- `lastName`
- `position`
- `teamStints`

Observed behavior:

- `searchTerm` is the usable query parameter
- name lookup can return a stable player identifier
- the response is suitable for portal-row crosswalking when a portal row lacks an explicit player ID

### Canonical team registry

The NCAAF team registry spec defines the canonical join backbone for origin and destination schools.

Required fields:

- `team_id`
- `canonical_team_name`
- `abbreviation`
- `conference`
- `subdivision`
- `aliases`

### Player identity snapshot

The live CFBD-backed player identity snapshot exists and contains:

- `player_id`
- `player_name`
- `team_id`
- `position`
- `season`

This snapshot is the preferred player anchor for transfer rows.

### Roster snapshot

The canonical roster snapshot now exists and contains:

- `player_id`
- `player_name`
- `team_id`
- `position`
- `season`
- `roster_status`
- `source_system`
- `source_snapshot_date`

This snapshot is the preferred roster anchor for transfer joins and continuity checks.

## Missing Data

The following transfer-specific data is still missing from the repository surface as a dedicated artifact layer:

- a canonical NCAAF transfer portal snapshot file
- a transfer-specific artifact path and manifest pointer
- a normalized transfer identifier in the transfer row itself
- a canonical transfer-status classification field beyond portal eligibility
- any explicit before/after roster resolution metadata

### Specifically missing transfer fields

The portal surface currently provides most of the needed transfer context, but the repository does not yet publish a dedicated transfer artifact with all of the following normalized fields on each row:

- `transfer_id` or equivalent stable portal-row identifier
- `player_id`
- `player_name`
- `origin_team_id`
- `destination_team_id`
- `transfer_date`
- `season`
- `position`
- `eligibility`

### What CFBD does and does not provide

CFBD does provide:

- portal movement
- origin school
- destination school
- transfer date
- eligibility
- position

CFBD does not provide a stable transfer identifier in the portal payload that we observed, so the onboarding layer must create a deterministic row key from the available fields or resolve the player through the player-search surface.

## Join Requirements

### Join to canonical team registry

Transfer rows must join origin and destination schools to the canonical NCAAF team registry.

Required behavior:

- normalize `origin` to `origin_team_id`
- normalize `destination` to `destination_team_id`
- preserve the canonical registry IDs after matching
- fail validation when either team cannot be resolved uniquely

### Join to player identity snapshot

Transfer rows must resolve to a canonical player identity row.

Required behavior:

- `player_id` is preferred when a crosswalk exists
- `player_name` is the fallback matching key
- `position` should align with the identity snapshot when possible
- `season` must match the portal season being onboarded

### Join to roster snapshot

Transfer rows must also resolve against the roster snapshot so transfer movement can be tied to the current roster cut.

Required behavior:

- the player must exist in the roster snapshot for the season being analyzed, or be explicitly marked as an incoming/outgoing edge case
- roster status should distinguish active roster membership from portal movement history
- transfer rows should carry the roster and identity keys used to connect movement to continuity layers

### Join priority

Recommended join order:

1. resolve `player_id` through player-search or an existing identity crosswalk
2. resolve `origin` and `destination` through the canonical team registry
3. resolve the same player in the roster snapshot
4. store the normalized transfer artifact row only after all required joins are satisfied or explicitly marked unresolved

## Validation Requirements

The canonical transfer portal snapshot must pass the following checks before publication:

### Structural checks

- the artifact exists as a dedicated transfer snapshot file
- every row contains the required transfer fields
- the file is parseable as CSV or JSON according to the implementation contract

### Identity checks

- `player_name` is present for every row
- `origin_team_id` resolves to the canonical team registry
- `destination_team_id` resolves to the canonical team registry
- `position` is present and usable by the football player pipeline
- `eligibility` is present for every row or explicitly marked unknown

### Crosswalk checks

- portal rows can be crosswalked to `player_id` through player search when needed
- portal rows can be matched back to the roster snapshot
- portal rows can be matched back to the canonical team registry through both source and destination schools

### Coverage checks

- the portal data is season-dated
- the portal dataset covers the intended transfer window
- duplicate portal rows are handled deterministically
- incomplete portal rows are not silently promoted

### Provenance checks

- source system is recorded as `cfbd`
- source snapshot date is recorded
- origin, destination, transfer date, and eligibility are preserved from the upstream feed

## Risks

### Risk 1: Portal rows may not carry a stable player identifier

The live CFBD portal feed exposes movement context, but not a stable player ID in the observed payload.

That means the transfer layer must rely on a player-search crosswalk or a deterministic row key.

### Risk 2: Origin and destination labels must be normalized carefully

Portal labels may use school names or provider variants that do not match the canonical registry directly.

### Risk 3: Eligibility is useful but not sufficient as transfer status

Eligibility is a strong portal attribute, but it is not a complete transfer-state model by itself.

### Risk 4: Season overlap can create duplicate identity edges

A player may appear in portal data and roster data across different season cuts, so the transfer artifact needs explicit season handling.

## M5 Readiness Assessment

M5 is not ready.

### What is ready

- canonical team registry exists
- canonical player identity snapshot exists
- canonical roster snapshot exists
- CFBD exposes a live transfer portal feed
- CFBD player search can be used as a player-ID crosswalk

### What is not ready

- no canonical transfer portal artifact exists yet
- no transfer-specific row key or manifest pointer exists yet
- no deterministic publication path for portal rows exists yet

### Readiness judgment

Transfer onboarding can be defined from CFBD, but it cannot yet be declared complete without a canonical transfer artifact.

## Final Answers

### Can transfer onboarding be completed from CFBD?

Yes, CFBD exposes enough live transfer-portal data to support onboarding: origin, destination, transfer date, position, and eligibility are available, and player-search can supply a player ID crosswalk.

### What transfer artifact must exist?

A canonical NCAAF transfer portal snapshot, likely named `ncaaf_transfer_portal_snapshot.csv`, should exist under the NCAAF source artifact tree and contain normalized transfer rows with player identity, origin and destination team IDs, transfer date, eligibility, season, and provenance.

### What remains before M4 can be declared complete?

The repository still needs the transfer artifact itself, the deterministic player crosswalk/publish path, and validation that the portal rows join cleanly to the team registry, player identity snapshot, and roster snapshot.
