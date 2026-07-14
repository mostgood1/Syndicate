# NCAAF Week 1 Publication Readiness Report

## Scope

Week 1 market coverage contains 13 unique game pairs in the local recommendation slice.

Observed market and feature status:

- Total Week 1 matched games: 13
- Tier A games: 8
- Tier C games: 5
- Tier B games: 0
- Tier D games: 0

## Week 1 Game Classification

### Tier A - Publishable

- Western Michigan @ Michigan State
- Kennesaw State @ Wake Forest
- UNLV @ Sam Houston
- San Jose State @ Central Michigan
- Tennessee @ Syracuse
- Ball State @ Purdue
- Coastal Carolina @ Virginia
- Eastern Michigan @ Texas State

Coverage status:

- full team registry mapping
- full player identity coverage
- full roster coverage
- full transfer coverage
- full returning production coverage
- full coach continuity coverage
- matched market recommendation row

Publication status:

- publishable now
- no warning required

### Tier C - Suppressed

- Tarleton State @ Army
- Bethune-Cookman @ Florida International
- Nicholls @ Troy
- SE Louisiana @ Louisiana Tech
- Bryant @ New Mexico State

Coverage status:

- team registry mapping resolves
- market row exists
- one or more secondary feature layers are missing
- missing layers are concentrated in returning production and coach continuity, with transfer coverage also missing on selected teams

Publication status:

- do not publish in the production board
- keep in audit / backfill views only

## Missing Layers By Blocked Game

### Tarleton State @ Army

- Tarleton State: missing returning production
- Tarleton State: missing coach continuity
- Army: missing destination-side transfer coverage

### Bethune-Cookman @ Florida International

- Bethune-Cookman: missing returning production
- Bethune-Cookman: missing coach continuity

### Nicholls @ Troy

- Nicholls: missing returning production
- Nicholls: missing coach continuity

### SE Louisiana @ Louisiana Tech

- SE Louisiana: missing transfer coverage
- SE Louisiana: missing returning production
- SE Louisiana: missing coach continuity

### Bryant @ New Mexico State

- Bryant: missing returning production
- Bryant: missing coach continuity

## Publication Rules Applied To Week 1

1. Tier A games are publishable now.
2. Tier C games are suppressed.
3. No Tier B games were identified in the current Week 1 slice.
4. No Tier D games were identified in the current Week 1 slice.
5. Because the blocked games are driven by feature coverage gaps, not registry or model defects, the publication framework should not force them through with degraded confidence.

## Confidence Treatment

Tier A games receive full confidence.

Tier C games should not be assigned a normal public board confidence because their missing layers are material and concentrated in the exact features used to support board publication.

Recommended board behavior:

- Tier A: standard confidence presentation
- Tier C: suppressed, not downgraded into a public board card

## Minimum Feature Set Required For Publication

A Week 1 game is publishable only when all of the following are true:

- both teams resolve in the published team registry
- player identity exists for both teams
- roster exists for both teams
- transfer coverage exists for both teams
- returning production exists for both teams
- coach continuity exists for both teams
- the game has a matching market recommendation row

That is the minimum feature set required for Tier A publication.

## Answers

How many Week 1 games are publishable now?

- 8

Which games are Tier A?

- Western Michigan @ Michigan State
- Kennesaw State @ Wake Forest
- UNLV @ Sam Houston
- San Jose State @ Central Michigan
- Tennessee @ Syracuse
- Ball State @ Purdue
- Coastal Carolina @ Virginia
- Eastern Michigan @ Texas State

Which games require reduced confidence?

- None in the current Week 1 slice.

Which games should not be published?

- Tarleton State @ Army
- Bethune-Cookman @ Florida International
- Nicholls @ Troy
- SE Louisiana @ Louisiana Tech
- Bryant @ New Mexico State

What is the minimum feature set required for publication?

- full team registry mapping
- player identity coverage for both teams
- roster coverage for both teams
- transfer coverage for both teams
- returning production coverage for both teams
- coach continuity coverage for both teams
- a matching market recommendation row

## Final Answer

NCAAF Week 1 is ready to enter production board publication only for the 8 Tier A games. The remaining 5 games should stay suppressed until their missing feature layers are backfilled.