# NCAAF Phase 4 Board Validation Report

## Week 1 Board Snapshot

Week 1 contains 13 matched board candidates in the local NCAAF slice:

- 8 Tier A publishable games
- 5 Tier C suppressed games
- 0 Tier B games
- 0 Tier D games

The current coverage-aware board contract keeps all Tier A games ahead of all Tier C games.

### Publishable Candidates

| Final Rank | Matchup | Model Edge | Confidence | Coverage Score | Tier | Publication Priority |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| 1 | UNLV @ Sam Houston | 13.4466 | 0.8869 | 1.0000 | A | 3 |
| 2 | Syracuse @ Tennessee | 11.0170 | 0.8000 | 1.0000 | A | 3 |
| 3 | Coastal Carolina @ Virginia | 8.7174 | 0.9626 | 1.0000 | A | 3 |
| 4 | San Jose State @ Central Michigan | 5.7748 | 0.7827 | 1.0000 | A | 3 |
| 5 | Eastern Michigan @ Texas State | 3.9030 | 1.0000 | 1.0000 | A | 3 |
| 6 | Western Michigan @ Michigan State | 2.0546 | 0.8342 | 1.0000 | A | 3 |
| 7 | Ball State @ Purdue | 1.3991 | 0.9363 | 1.0000 | A | 3 |
| 8 | Kennesaw State @ Wake Forest | 0.3238 | 0.7755 | 1.0000 | A | 3 |

### Suppressed Candidates

| Legacy Rank | Matchup | Model Edge | Confidence | Coverage Score | Tier | Publication Priority |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| 4 | SE Louisiana @ Louisiana Tech | 7.6612 | 0.8108 | 0.6750 | C | 1 |
| 5 | Nicholls @ Troy | 6.6544 | 1.0000 | 0.6750 | C | 1 |
| 6 | Bethune-Cookman @ Florida International | 6.4788 | 0.9755 | 0.6750 | C | 1 |
| 8 | Bryant @ New Mexico State | 5.6662 | 0.8588 | 0.6750 | C | 1 |
| 11 | Tarleton State @ Army | 1.7488 | 0.8864 | 0.6750 | C | 1 |

## Ranking Analysis

Legacy board ordering would have sorted the Week 1 slice by model edge alone and produced this order:

1. UNLV @ Sam Houston
2. Syracuse @ Tennessee
3. Coastal Carolina @ Virginia
4. SE Louisiana @ Louisiana Tech
5. Nicholls @ Troy
6. Bethune-Cookman @ Florida International
7. San Jose State @ Central Michigan
8. Bryant @ New Mexico State
9. Eastern Michigan @ Texas State
10. Western Michigan @ Michigan State
11. Tarleton State @ Army
12. Ball State @ Purdue
13. Kennesaw State @ Wake Forest

Coverage-aware ordering changes that outcome in a meaningful way:

- All 8 Tier A games are lifted above all 5 Tier C games.
- San Jose State @ Central Michigan moves up from legacy rank 7 to final rank 4.
- Eastern Michigan @ Texas State moves up from legacy rank 9 to final rank 5.
- Western Michigan @ Michigan State moves up from legacy rank 10 to final rank 6.
- Ball State @ Purdue moves up from legacy rank 12 to final rank 7.
- Kennesaw State @ Wake Forest moves up from legacy rank 13 to final rank 8.

## Coverage Impact Analysis

Coverage is doing real board work here.

- Tier A games have full feature coverage and remain publishable.
- Tier C games have material feature gaps and remain suppressed.
- The board no longer lets raw edge alone place a Tier C game ahead of a Tier A game.

This is the intended behavior for Phase 2.6 and Phase 3: coverage controls publication priority, while the model edge still breaks ties within the publishable tier.

## Publication Analysis

Publication behavior is consistent with the contract:

- Publish the 8 Tier A games.
- Suppress the 5 Tier C games.
- Do not downgrade Tier C into the public board with reduced confidence.

The current coverage-adjusted confidence values are also coherent:

- Tier A rows cluster near full confidence presentation.
- Tier C rows remain below the publishable threshold and are not surfaced as normal board cards.

## Anomaly Review

Observed anomalies are operational, not ranking defects:

- The live NCAAF candidate path is still blocked by an empty mirrored odds-history file.
- The broader intelligence query path still has an unrelated WNBA runtime failure if it is allowed to traverse all sports.
- There is no evidence that a Tier A game is being suppressed incorrectly or that a Tier C game is being published.

Ranking anomalies reviewed:

- Unexpectedly low-ranked Tier A games: none. The lowest Tier A games are low because their model edge is lower, not because coverage is hurting them.
- Unexpectedly high-ranked Tier C games: none on the coverage-aware board. They remain behind Tier A as intended.
- Confidence mismatches: none in the published Tier A slice; Tier C confidence remains secondary because those rows are suppressed.
- Publication inconsistencies: none in the current slice.

## Calibration Recommendations

1. Keep the coverage-aware board ordering exactly as implemented.
2. Preserve suppression for Tier C until the missing returning-production / coach-continuity / transfer layers are backfilled.
3. Persist a true betting EV field in the candidate artifact if future weekly calibration needs EV instead of the current model-edge proxy.
4. Add a durable Week 1 board snapshot artifact so future validations do not depend on reconstructing the slice from the totals CSV and readiness reports.
5. Fix the all-sport intelligence entrypoint or continue using a sport-limited board validation path for NCAAF.

## Explicit Answers

Is the SmartSim-aware board behaving as intended?

- Yes. Tier A is prioritized above Tier C, and coverage meaningfully shapes board order.

Are publication decisions consistent?

- Yes. All Tier A games publish, all Tier C games suppress.

Does coverage-aware ordering improve board quality?

- Yes. It removes low-coverage games from the public board and prevents raw edge from outranking better-covered candidates.

What remaining issues block production operation?

- The mirrored odds-history source is empty, so live candidate extraction is still blocked.
- The shared intelligence route can still fail on the unrelated WNBA path if it is not sport-limited.
- A persisted true-EV field is still missing, so weekly calibration uses a model-edge proxy.

Is NCAAF ready for ongoing weekly board generation?

- Not fully. The board logic is ready, but the current live data path is not reliable enough for routine weekly operation until the odds-history input and shared request path are stable.

## Final Verdict

The NCAAF SmartSim-aware board is behaving correctly for the current Week 1 slice. Coverage-aware ordering improves board quality and publication behavior, but production operation still needs a populated live odds-history source, a stable NCAAF-only board path, and a durable true-EV artifact before it can be treated as routine weekly infrastructure.