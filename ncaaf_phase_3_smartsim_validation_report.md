# NCAAF Phase 3 SmartSim Validation Report

## Scope

This report validates the current Week 1 NCAAF candidate slice against the coverage-aware ranking and publication rules introduced in Phase 2.6.

Source notes:

- The live NCAAF candidate path is currently blocked because the mirrored odds history file is empty.
- The Week 1 candidate set below is reconstructed from the latest mirrored predicted-totals artifact plus the stored Week 1 coverage-readiness reports.
- Expected value is shown as the stored model-edge proxy because the mirror does not contain live odds needed to recompute betting EV.

## Current Week 1 Board

| Pub Order | Matchup | Edge | EV proxy | Confidence | Coverage Score | Tier | Status |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| 1 | UNLV @ Sam Houston | 13.4466 | 4.7816 | 0.95 | 1.0000 | A | publishable |
| 2 | Syracuse @ Tennessee | 11.0170 | 11.4823 | 0.95 | 1.0000 | A | publishable |
| 3 | Coastal Carolina @ Virginia | 8.7174 | 19.3917 | 0.95 | 1.0000 | A | publishable |
| 4 | San Jose State @ Central Michigan | 5.7748 | 4.1859 | 0.95 | 1.0000 | A | publishable |
| 5 | Eastern Michigan @ Texas State | 3.9030 | 18.7007 | 0.95 | 1.0000 | A | publishable |
| 6 | Western Michigan @ Michigan State | 2.0546 | 8.9551 | 0.95 | 1.0000 | A | publishable |
| 7 | Ball State @ Purdue | 1.3991 | 19.4493 | 0.95 | 1.0000 | A | publishable |
| 8 | Kennesaw State @ Wake Forest | 0.3238 | 4.8940 | 0.95 | 1.0000 | A | publishable |
| 9 | SE Louisiana @ Louisiana Tech | 7.6612 | 17.5884 | 0.82 | 0.6750 | C | suppressed |
| 10 | Nicholls @ Troy | 6.6544 | 22.5864 | 0.82 | 0.6750 | C | suppressed |
| 11 | Bethune-Cookman @ Florida International | 6.4788 | 21.7926 | 0.82 | 0.6750 | C | suppressed |
| 12 | Bryant @ New Mexico State | 5.6662 | 17.5794 | 0.82 | 0.6750 | C | suppressed |
| 13 | Tarleton State @ Army | 1.7488 | 4.2768 | 0.82 | 0.6750 | C | suppressed |

## Coverage Tier Analysis

The board splits cleanly into 8 Tier A games and 5 Tier C games.

- Tier A is fully publishable.
- Tier C remains suppressed.
- Tier B and Tier D are absent from the current Week 1 slice.

The stored readiness reports are consistent with this split:

- Tier A: full registry, player identity, roster, transfer, returning-production, and coach-continuity coverage.
- Tier C: registry resolves and the market row exists, but one or more secondary feature layers are missing.

## Candidate Ranking Analysis

Publication ordering is behaving as expected:

- All Tier A games appear before all Tier C games.
- Within Tier A, higher edge surfaces first.
- Within Tier C, the games remain below the publishable set even when their raw edge is competitive.

The important check is that coverage is controlling visibility, not model math. High raw edge alone does not promote a Tier C game onto the public board.

## Confidence Analysis

Confidence is behaving as a coverage-aware presentation signal rather than a pure model-confidence mirror.

- Tier A cards land at the full coverage-adjusted confidence level.
- Tier C cards are reduced to the lower coverage-adjusted level and remain suppressed.
- This matches the Phase 2.6 contract: confidence should reinforce publication readiness, not override it.

## Publication Analysis

The publication contract is correct for this slice.

- Publish: the 8 Tier A games.
- Suppress: the 5 Tier C games.
- Do not create a public board card for Tier C games until the missing feature layers are backfilled.

## Anomaly Review

There are two operational anomalies, but neither changes the Week 1 tier decision:

- The live NCAAF candidate path is empty because the mirrored odds-history input has zero entries.
- The broader all-sport intelligence path has an unrelated WNBA crash, so a sport-limited validation path was required.

Bottom line:

- Phase 3 SmartSim validation is coherent for Week 1 coverage behavior.
- Tier A is publishable now.
- Tier C is correctly suppressed.
- No Tier B or Tier D games are present in the current Week 1 slice.