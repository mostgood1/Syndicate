# NCAAF Week 1 Join Gap Analysis

## Blocked Games

The following five Week 1 games are blocked from full board publication:

1. Tarleton State @ Army
2. Bethune-Cookman @ Florida International
3. Nicholls @ Troy
4. SE Louisiana @ Louisiana Tech
5. Bryant @ New Mexico State

## Root Cause Analysis

### 1. Tarleton State @ Army

Observed join failures:

- Army: missing transfer coverage on the destination side
- Tarleton State: missing returning production coverage
- Tarleton State: missing coach continuity coverage

Root cause:

- Source coverage gap in the derived feature layers for Tarleton State.
- Publication gap in transfer coverage for Army as a destination-side join.
- No evidence of a normalization or alias issue; both teams resolve through the published team registry.

Artifact trace:

- Team registry resolves both teams.
- Returning production does not cover Tarleton State.
- Coach continuity does not cover Tarleton State.
- Transfer portal coverage is incomplete for Army on the destination side.

Fix type:

- Data fix for Tarleton State feature coverage.
- Data fix or publication fix for Army destination transfer coverage.

### 2. Bethune-Cookman @ Florida International

Observed join failures:

- Bethune-Cookman: missing returning production coverage
- Bethune-Cookman: missing coach continuity coverage

Root cause:

- Source coverage gap in returning production and coach continuity for Bethune-Cookman.
- No evidence of a team-mapping or alias problem; the game resolves through the registry.

Artifact trace:

- Team registry resolves both teams.
- Returning production does not cover Bethune-Cookman.
- Coach continuity does not cover Bethune-Cookman.

Fix type:

- Data fix.

### 3. Nicholls @ Troy

Observed join failures:

- Nicholls: missing returning production coverage
- Nicholls: missing coach continuity coverage

Root cause:

- Source coverage gap in returning production and coach continuity for Nicholls.
- No alias or normalization issue was observed.

Artifact trace:

- Team registry resolves both teams.
- Returning production does not cover Nicholls.
- Coach continuity does not cover Nicholls.

Fix type:

- Data fix.

### 4. SE Louisiana @ Louisiana Tech

Observed join failures:

- SE Louisiana: missing transfer coverage on both origin and destination joins
- SE Louisiana: missing returning production coverage
- SE Louisiana: missing coach continuity coverage

Root cause:

- Source coverage gap across multiple feature layers for SE Louisiana.
- Transfer coverage is also incomplete for this team in the local artifact slice.
- No evidence of a normalization or alias problem; the registry resolves the team name.

Artifact trace:

- Team registry resolves both teams.
- Transfer portal does not cover SE Louisiana as a source-side or destination-side team in the published slice.
- Returning production does not cover SE Louisiana.
- Coach continuity does not cover SE Louisiana.

Fix type:

- Data fix.

### 5. Bryant @ New Mexico State

Observed join failures:

- Bryant: missing returning production coverage
- Bryant: missing coach continuity coverage

Root cause:

- Source coverage gap in returning production and coach continuity for Bryant.
- No team mapping or alias issue was observed.

Artifact trace:

- Team registry resolves both teams.
- Returning production does not cover Bryant.
- Coach continuity does not cover Bryant.

Fix type:

- Data fix.

## Required Fixes

The blocked games are not blocked by a single code defect.

Required remediation is mostly data coverage, not model code:

- Expand or backfill returning production for Tarleton State, Bethune-Cookman, Nicholls, SE Louisiana, and Bryant.
- Expand or backfill coach continuity for Tarleton State, Bethune-Cookman, Nicholls, SE Louisiana, and Bryant.
- Publish or backfill transfer coverage for Army as the destination-side join and for SE Louisiana on the missing transfer-side joins.

No alias or team-registry mapping changes are required for the five blocked games.

## Estimated Games Recoverable

Estimated recoverable blocked games after remediation: 5.

If the missing feature layers are backfilled for the affected teams, all five blocked games should become board-ready.

## Explicit Answers

Which 5 games are blocked?

- Tarleton State @ Army
- Bethune-Cookman @ Florida International
- Nicholls @ Troy
- SE Louisiana @ Louisiana Tech
- Bryant @ New Mexico State

Why is each game blocked?

- Tarleton State @ Army: Tarleton State is missing returning production and coach continuity, and Army is missing destination-side transfer coverage.
- Bethune-Cookman @ Florida International: Bethune-Cookman is missing returning production and coach continuity.
- Nicholls @ Troy: Nicholls is missing returning production and coach continuity.
- SE Louisiana @ Louisiana Tech: SE Louisiana is missing transfer coverage, returning production, and coach continuity.
- Bryant @ New Mexico State: Bryant is missing returning production and coach continuity.

Which fixes are data fixes versus code fixes?

- Data fixes: all five games require data coverage backfill.
- Code fixes: none were identified for the blocked-game root cause.

How many games would become board-ready after remediation?

- 5 games.

## Final Answer

The Week 1 join gaps are caused by missing feature coverage for specific smaller-program teams, not by registry normalization or board code defects. Backfilling those feature layers should recover all five blocked games.