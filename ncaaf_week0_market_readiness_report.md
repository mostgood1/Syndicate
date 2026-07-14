# NCAAF Week 0 Market Readiness Report

## Market Coverage

The current NCAAF schedule mirror in this workspace does not contain any Week 0 games.

Observed schedule coverage from `data/ncaaf_source/data/college_football_schedule_2025_predicted_totals_enhanced.csv`:

- Total schedule rows: 3,736
- Week 0 rows: 0
- Week 1 rows: 248
- Weeks present begin at Week 1

Because there are no Week 0 schedule rows, there are also no Week 0 board candidates to match against current odds sources in the local workspace.

## Feature Coverage

The NCAAF onboarding stack is complete and the six canonical artifacts are published:

- [ncaaf_team_registry.csv](data/ncaaf_source/source_artifacts/data/processed/team_registry/ncaaf_team_registry.csv)
- [ncaaf_player_identity_snapshot.csv](data/ncaaf_source/source_artifacts/data/processed/player_identity/ncaaf_player_identity_snapshot.csv)
- [ncaaf_roster_snapshot.csv](data/ncaaf_source/source_artifacts/data/processed/roster/ncaaf_roster_snapshot.csv)
- [ncaaf_transfer_portal_snapshot.csv](data/ncaaf_source/source_artifacts/data/processed/transfers/ncaaf_transfer_portal_snapshot.csv)
- [ncaaf_returning_production_snapshot.csv](data/ncaaf_source/source_artifacts/data/processed/returning_production/ncaaf_returning_production_snapshot.csv)
- [ncaaf_coach_continuity_snapshot.csv](data/ncaaf_source/source_artifacts/data/processed/coach_continuity/ncaaf_coach_continuity_snapshot.csv)

These artifacts are sufficient to support joins for board publication once Week 0 games exist in the schedule/odds surface.

## Join Validation

Join validation could not be executed for Week 0 games because the local schedule mirror contains no Week 0 rows.

Validated supporting evidence:

- Team registry is published and clean.
- Player identity, roster, transfer portal, returning production, and coach continuity snapshots are published and clean.
- The schedule mirror starts at Week 1, so there is no Week 0 row to join against the registry or the downstream feature layers.

## Remaining Gaps

The blocking gap is market availability, not onboarding completeness.

- No Week 0 games are present in the local NCAAF schedule mirror.
- Therefore no Week 0 odds rows can be matched locally.
- There are no Week 0 feature-complete games to publish from this workspace state.

## Publication Readiness

Current answer: no, a Week 0 board cannot be published today from the current local NCAAF data surface.

Reason:

- Week 0 games do not exist in the mirrored schedule source.
- Without Week 0 games, there are no board candidates to validate or publish, even though onboarding is complete.

## Explicit Answers

How many Week 0 games currently have odds?

0.

Which games are fully feature-complete?

None, because there are no Week 0 games in the current schedule mirror.

Which games are blocked by missing data?

All Week 0 games are blocked by the absence of Week 0 schedule rows in the local mirror.

Can a Week 0 board be published today?

No.

## Final Answer

The NCAAF onboarding stack is ready, but the current local market surface does not contain Week 0 games. Week 0 board publication is therefore not ready today.