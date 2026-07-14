# NCAAF Team Metadata Onboarding Report

## Purpose

This report completes the M2 team metadata onboarding review for NCAAF using the NFL onboarding process as the template.

Scope constraints:

- No football model changes.
- No NFL onboarding artifact changes.
- No recruiting work.
- No transfer portal work.
- No coaching continuity work.

## Current State

NCAAF team identity is present in the schedule and refresh artifacts, but it is not yet represented as a dedicated canonical team registry layer.

The current NCAAF path relies on schedule-row identity, refresh-time alias normalization, and lightweight UI abbreviations to render teams consistently enough for the current boards.

That is enough to bootstrap M2, but it is not yet a fully canonical identity layer.

## Available Metadata

### Team names

Team names are present in the NCAAF schedule and recommendations artifacts as `home_team` and `away_team` fields.

The refresh script also consumes the same names when it joins OddsAPI events to schedule rows.

### Abbreviations

The current NCAAF UI layer derives abbreviations heuristically when it renders cards and board tiles.

The fallback helper in `syndicate/features/ncaaf/cards.py` uses token initials or a three-letter uppercase slice when no richer identity layer exists.

That means abbreviations are available for display, but they are not yet backed by a dedicated canonical team registry.

### Conference identifiers

Conference context is partially present in the schedule artifacts.

The schedule report shows that schedule rows already expose conference-related labels such as `conference_game` and conference names in the row payloads.

That is enough to begin normalization, but not enough to claim a standalone conference identity contract.

### Aliases

The refresh path already contains explicit alias normalization for college-team names.

Examples include:

- `utsa` -> `texas san antonio`
- `ut san antonio` -> `texas san antonio`
- `uconn` -> `connecticut`
- `miami oh` -> `miami ohio`
- `penn st` -> `penn state`
- `texas a&m` -> `texas am`
- `oregon ducks` -> `oregon`
- `miami hurricanes` -> `miami`
- `georgia bulldogs` -> `georgia`
- `alabama crimson tide` -> `alabama`

This alias map is the strongest existing identity-normalization signal in the current NCAAF source path.

### School naming inconsistencies

The current data path shows the kinds of inconsistencies M2 must normalize:

- nickname-heavy names versus school names
- abbreviated names versus full school names
- conference-adjacent labels versus school identity labels
- provider naming that may differ from schedule naming
- UI display abbreviations that are generated heuristically rather than sourced from a registry

The refresh logic already handles many of these mismatches by normalizing away nicknames and alias variants before matching schedule rows to OddsAPI events.

## Conference Support

Conference support is partial, not canonical.

The schedule artifacts carry conference-related context, but the repository does not yet show a dedicated NCAAF conference registry or conference snapshot artifact.

That means conference identity currently behaves as schedule metadata, not as a first-class normalized team metadata layer.

For M2, that is acceptable as bootstrap input. For M3 and later roster joins, it is not enough on its own.

## Identity Normalization Requirements

### What the current system already does

- normalizes provider team names before schedule matching
- matches odds rows to schedule rows using normalized home/away names
- preserves canonical schedule names once the match is found
- derives display abbreviations for UI surfaces when no registry exists

### What a canonical NCAAF identity layer still needs

- a season-dated team registry
- canonical team name
- canonical short name or school name
- canonical abbreviation
- alias list per team
- conference membership for the season
- stable crosswalks between provider names, school names, nicknames, and UI abbreviations

### Why this matters

Without a canonical identity layer, the same team can appear under multiple names across schedule rows, refresh rows, summary rows, and UI tiles.

That makes downstream joins fragile and creates avoidable drift before roster onboarding begins.

## Recommended Canonical Team Mapping

The recommended canonical mapping is:

- `team_id`: stable internal canonical identifier, ideally season-aware
- `team_name`: official school or program name used as the primary display name
- `team_abbr`: canonical short abbreviation used across shared football contracts
- `conference`: season conference membership
- `aliases`: all known provider and nickname variants
- `source_names`: raw names seen in schedule, summary, and refresh artifacts
- `display_name`: user-facing name used in cards and boards

### Mapping rules

1. Canonicalize from the schedule row first.
2. Apply the refresh alias map when matching provider data to schedule rows.
3. Preserve one canonical school/program name for the shared football framework.
4. Derive display abbreviations from the canonical mapping, not from UI-only heuristics.
5. Keep conference membership attached to the team record for the season.

### Practical recommendation

The canonical NCAAF mapping should be a dedicated team registry artifact, even if it is initially bootstrapped from the schedule artifacts.

The schedule rows can seed the registry, but they should not remain the registry forever.

## Can Existing Schedule Artifacts Bootstrap Team Metadata?

Yes.

The existing schedule artifacts already provide enough team names, home/away structure, and conference context to bootstrap a first-pass team metadata layer.

They can also seed initial canonical names and alias discovery.

What they cannot do by themselves is guarantee a stable canonical registry for all downstream joins.

## Is a Standalone NCAAF Team Registry Required?

Yes.

A standalone NCAAF team registry is required if the goal is to make team identity canonical rather than opportunistic.

The current schedule-driven approach is enough for M1 and enough to bootstrap M2, but it is not strong enough for roster onboarding, transfer joins, or longer-lived season consistency without a registry.

## What Must Exist Before NCAAF Roster Onboarding Can Begin?

Before M3 roster onboarding can begin, the following must exist:

- a canonical team registry with stable team IDs
- canonical team names and abbreviations
- season conference membership for each team
- alias crosswalks for provider and school naming variants
- schedule rows normalized against the canonical team registry
- a stable game identity that can join roster rows to team identity

Roster onboarding depends on the team layer because roster rows need a stable home team anchor and season context.

## M3 Readiness Assessment

M3 is not ready yet.

### Ready enough for bootstrap

- the schedule artifacts can seed team names
- the refresh alias map can normalize provider names
- the UI can render abbreviations from the current schedule-backed surface

### Not ready for roster onboarding

- no dedicated NCAAF team registry exists in the current repo surface
- no canonical season team snapshot exists yet
- conference context is still schedule metadata rather than a formal identity layer

### Readiness judgment

M2 is partially complete and ready for bootstrap.

M3 should not start until the team registry and canonical team mapping exist, because roster rows need stable team anchors and the shared football framework needs a consistent identity contract.

## Final Answer

Existing schedule artifacts can bootstrap NCAAF team metadata, but they should not remain the final identity source.

A standalone NCAAF team registry is required to make team identity canonical and stable across schedule, roster, and future program-context layers.

Before M3 roster onboarding can begin, NCAAF must have a canonical team registry, canonical abbreviations, season conference membership, and alias crosswalks anchored to stable team IDs.
