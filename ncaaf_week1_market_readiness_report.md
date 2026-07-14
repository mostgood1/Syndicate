# NCAAF Week 1 Market Readiness Report

## Market Coverage

Week 1 is the first market slice present in the mirrored NCAAF schedule data for this workspace.

Observed coverage:

- Total schedule rows: 3,736
- Week 0 rows: 0
- Week 1 rows: 248
- Recommendation rows for Week 1: 50
- Unique Week 1 game pairs in recommendations: 13
- Matched Week 1 games against schedule: 13

Week 1 market coverage exists, but it is incomplete relative to the full schedule slice.

## Feature Coverage

The newly published NCAAF onboarding stack is available for join validation:

- [ncaaf_team_registry.csv](data/ncaaf_source/source_artifacts/data/processed/team_registry/ncaaf_team_registry.csv)
- [ncaaf_player_identity_snapshot.csv](data/ncaaf_source/source_artifacts/data/processed/player_identity/ncaaf_player_identity_snapshot.csv)
- [ncaaf_roster_snapshot.csv](data/ncaaf_source/source_artifacts/data/processed/roster/ncaaf_roster_snapshot.csv)
- [ncaaf_transfer_portal_snapshot.csv](data/ncaaf_source/source_artifacts/data/processed/transfers/ncaaf_transfer_portal_snapshot.csv)
- [ncaaf_returning_production_snapshot.csv](data/ncaaf_source/source_artifacts/data/processed/returning_production/ncaaf_returning_production_snapshot.csv)
- [ncaaf_coach_continuity_snapshot.csv](data/ncaaf_source/source_artifacts/data/processed/coach_continuity/ncaaf_coach_continuity_snapshot.csv)

Feature-complete Week 1 games are those whose home and away teams resolve through the team registry and whose feature layers are present for both teams.

Observed fully feature-complete Week 1 games:

- Western Michigan @ Michigan State
- Kennesaw State @ Wake Forest
- UNLV @ Sam Houston
- San Jose State @ Central Michigan
- Tennessee @ Syracuse
- Ball State @ Purdue
- Coastal Carolina @ Virginia
- Eastern Michigan @ Texas State

Count: 8

## Join Validation

Join validation was performed against:

- schedule
- team registry
- roster snapshot
- transfer portal snapshot
- returning production snapshot
- coach continuity snapshot

Join results for the 13 matched Week 1 games:

- 8 games are fully feature-complete.
- 5 games are blocked by missing feature coverage.
- 235 Week 1 schedule rows do not currently map to recommendation rows in the local market slice.

Blocked Week 1 games:

- Tarleton State @ Army, missing returning production and coach continuity coverage for one side
- Bethune-Cookman @ Florida International, missing returning production and coach continuity coverage for one side
- Nicholls @ Troy, missing returning production and coach continuity coverage for one side
- SE Louisiana @ Louisiana Tech, missing returning production, coach continuity, and transfer coverage for one side
- Bryant @ New Mexico State, missing returning production and coach continuity coverage for one side

## Remaining Gaps

The current Week 1 market surface is blocked by two separate issues:

- Coverage is limited to 50 recommendation rows, which only produce 13 unique Week 1 game pairs.
- Five of those matched games still have missing feature coverage on at least one side.

The main missing feature layers are:

- returning production for non-FBS or otherwise uncovered teams in the matched market slice
- coach continuity for those same uncovered teams
- transfer coverage for at least one matched game

## Publication Readiness

Current answer: no, a fully feature-complete Week 1 board should not be published today from the current local slice.

Reason:

- There are only 13 matched Week 1 game pairs in the local market surface.
- Only 8 of those games are fully feature-complete.
- 5 matched games are still blocked by missing feature coverage.

## Explicit Answers

How many Week 1 games currently have odds?

13 unique game pairs in the local recommendation slice.

Which games are fully feature-complete?

- Western Michigan @ Michigan State
- Kennesaw State @ Wake Forest
- UNLV @ Sam Houston
- San Jose State @ Central Michigan
- Tennessee @ Syracuse
- Ball State @ Purdue
- Coastal Carolina @ Virginia
- Eastern Michigan @ Texas State

Which games are blocked by missing data?

- Tarleton State @ Army
- Bethune-Cookman @ Florida International
- Nicholls @ Troy
- SE Louisiana @ Louisiana Tech
- Bryant @ New Mexico State

Can a Week 1 board be published today?

Not as a fully feature-complete board.

## Final Answer

Week 1 is partially ready for board publication, but not fully ready for a clean publish/modeling pass. Eight games are feature-complete, five matched games remain blocked, and the local market slice is too thin to treat the full Week 1 board as ready today.