# NCAAF Roster Onboarding Report

## Purpose

This report completes the M3 roster onboarding analysis for NCAAF using the existing schedule, team-metadata, and team-registry work as the template.

Scope constraints:

- No code changes.
- No football model changes.
- No recruiting work.
- No transfer work.
- No coaching work.

## Current State

NCAAF roster onboarding is not yet available from the current repository surface.

The NCAAF data path is still schedule-first and summary-first. It has usable team identity normalization and display heuristics, but it does not yet expose a dedicated roster snapshot layer that can be used to resolve player identity, team assignment, and position coverage for the full season.

The canonical team registry spec now defines the identity backbone that roster onboarding will need, but that registry still does not exist as a visible artifact in the NCAAF source tree.

## Available Data

### NCAAF schedule artifacts

The NCAAF source root contains schedule and summary artifacts such as:

- `college_football_schedule_2025_predicted_totals_enhanced.csv`
- timestamped schedule refresh variants
- `recommendations_latest.json`
- `recommendations_2025.csv`
- `recommendations_summary/index.json`
- weekly `recommendations_summary/week_*.json` files

These artifacts provide:

- team names
- home and away references
- conference labels in the schedule rows
- refresh history
- matchup context that can seed team identity normalization

### Team identity artifacts

The refresh path already contains a substantial alias-normalization table for college-team names.

The NCAAF UI layer also derives abbreviations heuristically from team names when no stronger registry exists.

That means team identity is partially available and can support bootstrap normalization, but it is not the same thing as a roster source.

### NCAAF source roots

The NCAAF source tree currently shows:

- `data/`
- `manifests/`
- `source_artifacts/`

Within that tree, the visible content is schedule and summary oriented.

There is no visible NCAAF roster lane under the source root that mirrors the football roster snapshot expectations.

### Football-side reusable player contract

The shared football contract already supports player records through `FootballPlayerFeatures`, which includes:

- `player_id`
- `player_name`
- `team`
- `position`
- `usage_metrics`
- `market_features`
- `adapter_metadata`

So the contract shape is ready, but the NCAAF roster input layer is not.

## Missing Data

The following roster data is missing from the visible NCAAF repository surface:

- canonical 2026 or season-dated roster snapshot
- roster membership by player and team
- authoritative player identifiers
- authoritative player-to-team crosswalks
- roster status by date or season cut
- position coverage for the full roster set
- roster validation artifact that proves complete team/player coverage

### Specifically missing roster fields

The current NCAAF source surface does not visibly provide a dedicated dataset with all of the following on each player row:

- `player_id`
- `player_name`
- `team`
- `position`

The repository may contain player names incidentally inside other data products, but that is not equivalent to a roster snapshot.

### Missing season coverage

There is no visible NCAAF roster artifact proving complete player coverage for a season window.

That means roster onboarding cannot yet prove that all teams and all relevant players are represented.

## Team Registry Compatibility

The new NCAAF team registry spec is the correct identity backbone for roster onboarding, but it is not sufficient by itself.

### What is compatible today

- schedule rows can seed team names
- the alias map can normalize provider naming variants
- the canonical registry can supply stable team IDs once it exists
- the football player contract already accepts roster-shaped player fields

### What is not yet compatible

- no roster source is visible that can actually join to the registry
- no canonical roster snapshot exists to prove player-to-team assignment
- no roster-specific crosswalk exists for player identity resolution

### Compatibility verdict

The registry spec is compatible with the eventual roster layer, but the roster layer itself is absent.

That means M3 is blocked by missing source data, not by a contract mismatch.

## Can Roster Onboarding Be Bootstrapped From Existing Artifacts?

Only partially, and not to completion.

### What can be bootstrapped

- team names
- canonical team IDs once the registry is published
- conference context for team assignment
- alias-based team normalization

### What cannot be bootstrapped

- complete player identity coverage
- roster membership by team
- authoritative player IDs
- authoritative position coverage
- season-valid roster completeness

### Practical conclusion

Existing artifacts can bootstrap team identity inside roster onboarding, but they cannot bootstrap the roster itself.

That means the answer to the bootstrap question is yes for team identity, no for roster completion.

## Validation Requirements

Before roster onboarding can be considered valid, the following checks must pass:

### Structural checks

- a canonical NCAAF roster artifact exists
- the artifact is season-dated
- each row contains at least `player_id`, `player_name`, `team`, and `position`
- the artifact can be parsed consistently by the roster loader path

### Identity checks

- `player_id` resolves when present
- `player_name` remains available as a fallback
- `team` resolves through the canonical NCAAF team registry
- `position` is usable by the current player-feature path

### Coverage checks

- the roster covers the intended season window
- the roster includes players needed to build non-empty player features
- the roster is broad enough to represent the full team set, not only known game participants

### Crosswalk checks

- roster rows can match back to schedule teams through the registry
- roster rows can later match transfer and recruiting context through the same team backbone
- the roster does not require UI abbreviations or schedule-only heuristics to remain stable

## Risks

### Risk 1: Schedule artifacts may be mistaken for roster coverage

The current NCAAF surface is rich enough to suggest identity resolution, but it does not actually provide a roster snapshot.

That creates a risk of overestimating readiness if schedule rows are treated as player coverage.

### Risk 2: UI abbreviations are not a roster identity source

The current NCAAF cards and board layers can render abbreviations heuristically, but that should not be interpreted as a canonical roster or player identity layer.

### Risk 3: Missing player IDs will make future joins fragile

Without a real roster snapshot, player ID stability and team assignment stability cannot be proven.

### Risk 4: Roster completeness cannot be validated from existing artifacts alone

The available NCAAF artifacts do not prove that all expected players are present for the season.

## M4 Readiness Assessment

M4 is not ready.

### What is ready

- the canonical team registry design exists
- schedule artifacts can seed team identity
- the football contract can already carry player features
- alias-based team normalization is available

### What is not ready

- no canonical NCAAF roster snapshot exists
- no roster-to-team crosswalk exists
- no player-level season coverage can be proven
- no roster validation artifact exists

### Readiness judgment

Roster onboarding cannot complete from the current data alone.

The true blocker is the absence of a canonical roster snapshot or equivalent roster source that can be joined to the new team registry.

## Final Answers

### What must exist before NCAAF roster onboarding is complete?

At minimum, NCAAF roster onboarding requires:

- a canonical NCAAF team registry with stable team IDs
- a season-dated roster snapshot
- `player_id`, `player_name`, `team`, and `position` on every roster row
- roster-to-team joins resolved through the canonical registry
- enough season coverage to represent the full roster set, not just a subset of known players

### Can roster onboarding proceed with current data?

No, not to completion.

Current data can bootstrap team identity and provide partial normalization, but it does not provide a visible roster snapshot or authoritative player coverage.

### What are the true blockers?

The true blockers are:

- no canonical NCAAF roster artifact
- no player identity layer for the season
- no authoritative player-to-team assignment source
- no proven season-wide roster coverage
- no roster validation artifact that can confirm completeness
