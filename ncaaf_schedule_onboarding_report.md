# NCAAF Schedule Onboarding Report

## Purpose

This report completes the M1 schedule onboarding review for NCAAF using the NFL onboarding process as the template.

Scope constraints:

- No model changes.
- No recruiting work.
- No transfer portal work.
- No coaching continuity work.

## Current State

NCAAF schedule onboarding already has a real artifact surface, but it is still a schedule-first, artifact-backed lane rather than a fully formalized season onboarding contract.

The repository already contains NCAAF schedule CSVs, weekly summary payloads, and refresh history, and the football loader layer already knows how to turn game rows into `FootballSimulationInput` and `FootballGameFeatures`.

What is still missing is a dedicated canonical schedule contract for NCAAF that is clearly separated from the predicted-totals artifacts and validated as the production schedule source of truth.

## Available Data

### NCAAF schedule artifacts

The NCAAF source root at `data/ncaaf_source/` already contains:

- `data/college_football_schedule_2025_predicted_totals_enhanced.csv`
- many timestamped schedule refresh variants named `college_football_schedule_2025_predicted_totals_enhanced_*.csv`
- `data/recommendations_latest.json`
- `data/recommendations_2025.csv`
- `data/recommendations_summary/index.json`
- weekly recommendation summary files under `data/recommendations_summary/week_*.json`
- `manifests/`
- `source_artifacts/`

The `recommendations_summary/index.json` payload shows week-by-week refresh history, including fetch status and preserved/written row counts. That makes it the best visible refresh ledger for M1 onboarding today.

### Refresh history observations

The summary history shows that:

- week 1 produced rows and matched games
- later weeks often produced zero matches in the captured history
- the refresh process records both stdout and stderr from the fetch step
- the process retains enough history to explain why a week did or did not populate

### Canonical schedule source

The most plausible canonical schedule source today is the predicted schedule artifact family under `data/ncaaf_source/data/college_football_schedule_2025_predicted_totals_enhanced*.csv`.

That said, the repository still treats these as schedule-adjacent prediction artifacts, not as a formally declared NCAAF schedule contract. M1 should therefore treat them as the working source of truth until a dedicated schedule snapshot contract is introduced.

### Season coverage

Visible artifacts in the repository are concentrated around 2025 NCAAF schedule output.

The summary index and timestamped CSVs indicate repeated refreshes across the 2025 season window, with the default season resolver in `syndicate/features/ncaaf/sources.py` deriving season from the summary index or from the generated timestamp.

### Conference coverage

Conference information is partially present in the schedule artifacts.

The visible schedule rows already expose conference-related labels such as `conference_game` and conference names in the schedule row payloads, which is enough to start normalization.

What is missing is a dedicated conference registry or season conference snapshot that can be validated independently from the schedule CSVs.

### Game identifiers

NCAAF schedule rows have enough structure to build a game identity, but the repository does not yet show a dedicated canonical NCAAF game-id contract.

The football loader layer uses a deterministic game identity pattern derived from season, week, and home/away team context when it groups or materializes rows.

### Data refresh process

The refresh process is implemented in `scripts/refresh_ncaaf_oddsapi.py`.

It currently:

- fetches OddsAPI NCAAF rows using `sport=americanfootball_ncaaf`
- writes or refreshes `college_football_betting_lines_2025.csv`
- preserves prior rows when new data does not fully replace the existing lane
- copies the relevant NCAAF artifacts into the artifact bundle root
- materializes `recommendations_summary/` outputs
- records refresh state so later runs can determine whether recomputation is needed

This is a refresh-and-materialize workflow, not a separate schedule builder.

## Contract Mapping

### FootballSimulationInput

The shared football contract already defines `FootballSimulationInput` as the top-level season/date container.

For NCAAF M1, schedule rows map into that contract as follows:

- `sport`: `ncaaf`
- `date`: the selected simulation date or season selection date
- `games`: one `FootballGameFeatures` object per resolved matchup
- `players`: usually empty for M1 schedule onboarding unless player-level artifacts are also available
- `metadata`: season, week, selection, and source-context fields
- `adapter_metadata`: schedule source, summary index context, and refresh provenance

### FootballGameFeatures

NCAAF schedule rows map into `FootballGameFeatures` with the same shared football shape used by NFL.

The current football contract already exposes:

- `game_id`
- `home_team`
- `away_team`
- `team_metrics`
- `defensive_metrics`
- `advanced_metrics`
- `matchup_metrics`
- `market_features`
- `pace_features`
- `epa_per_play`
- `success_rate_value`
- `proe_value`
- `red_zone_efficiency_value`
- `explosive_play_rate_value`
- `home_team_features`
- `away_team_features`
- `adapter_metadata`

For NCAAF schedule onboarding, most of those fields should be populated from schedule and market context only, with team and advanced metrics remaining empty or placeholder until later milestones.

The schedule-specific parts of the mapping are:

- `game_id`: deterministic identifier derived from season, week, and matchup
- `home_team` / `away_team`: canonical team names or abbreviations from the schedule row
- `market_features`: betting and line context if the schedule row comes from the predicted-totals lane
- `adapter_metadata`: source file, refresh provenance, season, week, and conference metadata

### FootballTeamFeatures

If team sub-features are produced during M1, they should only carry schedule-safe identity and market context.

For NCAAF schedule onboarding, `FootballTeamFeatures` should not be expected to contain mature offensive or defensive metrics unless those are separately sourced.

### Historical loader path

The shared football loader already shows the mapping logic that NCAAF can reuse:

- build a list of game dictionaries
- compute derived team metrics through the feature builder
- convert each game dictionary into `FootballGameFeatures`
- collect any player features only when player data is actually present

That means M1 can complete schedule onboarding without any model changes.

## Validation Requirements

M1 schedule onboarding should be validated with focused checks against the actual schedule artifact path.

### Required checks

- the NCAAF source root resolves to the expected `data/ncaaf_source/` artifact tree
- the predicted schedule CSV exists and is readable
- the weekly summary index contains usable refresh history
- the schedule rows include week, home team, away team, and conference context
- the refresh process still writes or preserves the NCAAF schedule artifacts
- schedule rows can be grouped into deterministic matchup identities
- the loader can materialize schedule rows into `FootballSimulationInput` with non-empty `games`

### Mapping checks

- `game_id` is stable for the same matchup row
- `home_team` and `away_team` are canonicalized consistently
- `adapter_metadata` records source provenance
- `metadata` carries the season and selection context
- `market_features` are retained when present in the schedule artifact

### Regression checks

- repeated refreshes do not break the canonical schedule lane
- the schedule lane remains compatible with the existing football loader expectations
- empty weeks remain representable without crashing the loader

## Risks

### Risk 1: Predicted schedule artifacts may be treated as canonical too early

The repository clearly has schedule-like artifacts, but they are still labeled as predicted totals and refresh outputs.

If M1 declares them canonical without a formal contract, later schedule normalization could become harder to reason about.

### Risk 2: Week coverage may be incomplete or sparse

The refresh history shows that some weeks produce rows while others do not.

That means the schedule lane may be partially populated, which is fine for onboarding but should be explicit in downstream validation.

### Risk 3: Conference and identity normalization may drift

The artifacts expose conference information, but not a dedicated conference registry.

Without a registry, team naming and conference labels may drift across refreshes unless the schedule contract explicitly normalizes them.

### Risk 4: Game identity is implied rather than declared

The loader can derive a usable game identity, but the repo does not yet show a dedicated NCAAF game-id specification.

If that is not formalized, downstream consumers may end up re-deriving the same identity in slightly different ways.

## M2 Readiness Assessment

M2 team metadata is partially ready, but not complete.

### What M2 already has

- team names in the schedule artifacts
- conference labels in the schedule artifacts
- enough schedule context to bootstrap canonical team normalization

### What M2 still lacks

- a dedicated team registry snapshot
- a dedicated conference registry snapshot
- a formal NCAAF metadata contract separate from schedule rows

### Readiness judgment

M2 is ready for planning and partial bootstrap, but not ready for a clean standalone completion claim.

The reason is simple: the schedule artifacts can seed team metadata, but they do not yet prove that the team metadata layer is formally canonicalized.

## Final Answer

NCAAF M1 schedule onboarding is viable now.

The repo already has the schedule artifact family, refresh history, and football contract shape needed to map NCAAF schedule rows into `FootballSimulationInput` and `FootballGameFeatures`.

The remaining gap is not model support. The remaining gap is formalizing the predicted-schedule artifacts into a clearly canonical NCAAF schedule contract and validating that the refresh process consistently produces the same schedule lane.
