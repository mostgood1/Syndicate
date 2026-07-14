# NCAAF Player Identity Source Report

## Purpose

This report determines where a canonical NCAAF player identity snapshot could realistically come from and whether the current NCAAF data surface can generate one.

Scope constraints:

- No code changes.
- No football model changes.
- No roster implementation.
- No recruiting implementation.
- No transfer implementation.
- No coaching implementation.

## Current State

The current NCAAF source surface is not player-identity complete.

What exists today is a schedule-first and summary-first artifact set with team names, conference context, alias normalization, and refresh history. That is enough to seed team identity, but not enough to create a canonical player identity snapshot for the season.

The canonical team registry spec and player identity spec now define the backbone and the minimum required shape, but the NCAAF source tree does not yet expose a visible player-level input that can satisfy those specs.

## Available Data

### NCAAF schedule artifacts

The NCAAF source root currently contains many `college_football_schedule_2025_predicted_totals_enhanced*.csv` files.

Those files provide:

- `season`
- `week`
- `start_date`
- `home_team`
- `away_team`
- `venue`
- `conference_game`
- weather and prediction columns

Later variants also expose additional schedule metadata such as:

- `home_conference`
- `away_conference`
- `start_date_api`
- `neutral_site`

These artifacts are useful for schedule and team identity, but they do not contain player identity fields.

### NCAAF recommendations summaries

The NCAAF recommendations summary artifacts provide:

- week-level recap data
- matchup context
- provider and market context
- refresh history

They are useful for board and schedule replay, but they do not provide season-wide player identity either.

### NCAAF refresh logic

The refresh path contains a strong alias-normalization table for college team names.

That means the current source path can normalize team references during schedule matching, but it does not surface a player identity layer.

### Shared football player contract

The football framework already supports player-shaped data through `FootballPlayerFeatures`, which can hold:

- `player_id`
- `player_name`
- `team`
- `position`
- `usage_metrics`
- `market_features`
- `adapter_metadata`

So the contract shape exists. The NCAAF player source does not.

## Sources Audited

### NCAAF source root

The visible NCAAF source root contains only:

- `data/`
- `manifests/`
- `source_artifacts/`

Within those directories, the visible content is schedule and summary oriented.

### NCAAF feature surface

The NCAAF feature code only uses team names and week/season context for cards, picks, live lens, archive, and betting-card views.

The UI layer derives abbreviations heuristically when needed, but that is a display fallback, not a player identity source.

### NCAAF data files

The visible NCAAF data files are schedule-like CSVs and weekly summary JSONs.

No visible NCAAF file contains a dedicated player roster snapshot or player identity table.

## Identity Fields Search Result

The audit did not find a visible NCAAF source that contains all of the following together:

- player identifiers
- player names
- team assignments
- positions
- season coverage

### What identity information already exists

- team names in schedule rows
- home and away references in schedule rows
- conference labels in schedule rows
- season and week context in schedule rows
- team alias normalization in the refresh path
- heuristic abbreviations in the UI layer

### What identity information is missing

- player identifiers
- player names for a season-wide player set
- player-to-team assignments
- authoritative positions
- season-dated player coverage
- a roster or player identity snapshot artifact

## Compatibility With the Specs

### Compatibility with ncaaf_player_identity_spec.md

The current source surface is compatible with the player identity spec only at the team-backbone level.

It is not compatible at the player layer because it lacks the required season-dated player snapshot and the required fields:

- `player_id`
- `player_name`
- `team_id`
- `position`
- `season`

### Compatibility with ncaaf_team_registry_spec.md

The current source surface is partially compatible with the team registry spec.

Schedule artifacts can seed canonical team names and aliases, but the registry spec still requires a dedicated canonical team registry artifact before roster onboarding can begin.

That means team identity is bootstrappable, while player identity is not.

## Can a Player Identity Layer Be Generated From Current Data?

No, not to completion.

### What can be inferred from current data

- season and week context
- team names and team aliases
- conference context
- matchup context
- limited display abbreviations

### What cannot be inferred from current data

- a complete season-wide player set
- authoritative player IDs
- authoritative player names
- player positions for all players
- player-to-team assignment for the season
- season-wide roster completeness

### Practical conclusion

The current data can support team identity normalization, but it cannot generate a canonical player identity snapshot.

## What Additional Data Is Required?

To create the canonical NCAAF player identity snapshot, the source path needs a dedicated player-facing artifact lane that provides at least:

- `player_id`
- `player_name`
- `team_id`
- `position`
- `season`

### Preferred additional source characteristics

- season-dated
- one row per player
- joinable to the canonical NCAAF team registry
- stable enough to support roster, transfer, recruiting, and coaching joins
- published as a dedicated snapshot artifact, not inferred from schedule rows

### Realistic source path

The realistic source path is a dedicated NCAAF player identity snapshot under the NCAAF source artifact tree, with a manifest pointer that marks it authoritative for the season.

That snapshot could be populated from a future roster feed, a curated school/player dataset, or a pipeline that produces a season roster cut, but none of those sources are visibly present in the current repository surface.

## What Artifact Must Exist Before Roster Onboarding Can Proceed?

The required artifact is a canonical season-dated NCAAF player identity snapshot.

### Required artifact behavior

- one row per player for the season
- includes `player_id`, `player_name`, `team_id`, `position`, and `season`
- joins to the canonical NCAAF team registry through `team_id`
- serves as the authoritative identity source for roster onboarding

### Why this artifact matters

Roster onboarding depends on player identity, not just team identity.

Without the snapshot, the system can normalize team context but cannot prove complete player identity or complete roster coverage.

## Source-Path Assessment

### What the current source path can do

- seed team names from schedule rows
- seed conference context from schedule rows
- normalize team aliases during schedule matching
- support heuristic display abbreviations

### What the current source path cannot do

- produce a canonical player identity snapshot
- prove roster completeness
- assign authoritative player IDs
- assign positions across the season
- establish player-to-team joins for the full season

### Source path verdict

The current NCAAF source path is sufficient for team identity bootstrap, but it is not sufficient for player identity generation.

## Risks

### Risk 1: Schedule artifacts may be mistaken for player coverage

The current NCAAF data surface is rich enough to look complete, but it is not player-complete.

### Risk 2: Heuristic abbreviations are not identity data

UI-derived abbreviations can help display, but they do not solve player identity.

### Risk 3: A partial player list would still be incomplete

Even if some player names appear incidentally in future artifacts, the snapshot must cover the full season set to be useful for roster onboarding.

### Risk 4: Missing registry linkage would keep player data unstable

Even a future player source is not enough unless it joins cleanly to the canonical team registry.

## Explicit Answers

### Can a player identity layer be generated from current data?

No. Current data can only infer team context and limited display naming, not a canonical player identity layer.

### What additional data is required?

A dedicated season-dated NCAAF player snapshot with `player_id`, `player_name`, `team_id`, `position`, and `season`, plus a manifest pointer that marks it authoritative.

### What artifact must exist before roster onboarding can proceed?

A canonical season-dated NCAAF player identity snapshot that joins to the canonical NCAAF team registry.

## Final Answer

The source path for the canonical NCAAF player identity snapshot does not exist yet in the current repository surface.

The only realistic path is a dedicated NCAAF player snapshot artifact under the NCAAF source artifact tree, backed by season-aware team registry linkage.

Until that snapshot exists, roster onboarding remains blocked.
