# NCAAF Coaching Source Validation Report

## Purpose

This report validates the currently available coaching source for M6 coaching continuity onboarding.

It answers whether the live coaching source can support season-dated coaching continuity on its own, and what additional source or derived layer would be required.

Scope constraints:

- No football model changes.
- No roster implementation.
- No transfer implementation.
- No returning-production implementation.
- No recruiting implementation.
- No NFL onboarding artifact changes.

## Live Coaching Source Probe

The live College Football Data API exposes a `/coaches` endpoint.

Observed probe results:

- `GET /coaches` returns a list of coach records.
- `GET /coaches?year=2025` returns season-filtered coach records.
- `GET /coaches?year=2025&team=Alabama` returns a single coach record for Alabama.
- `GET /coaches?year=2025&team=Wake Forest` returns a single coach record for Wake Forest.

### Observed top-level fields

The live payload consistently exposes these top-level fields:

- `firstName`
- `lastName`
- `hireDate`
- `seasons`

### Observed nested season fields

Each `seasons` entry contains season/team performance context, including:

- `school`
- `year`
- `games`
- `wins`
- `losses`
- `ties`
- `preseasonRank`
- `postseasonRank`
- `srs`
- `spOverall`
- `spOffense`
- `spDefense`

## What the Source Does Provide

The live coaching source does provide:

- coach identity fields for a record keyed by first and last name
- `hireDate` for at least some current coaches
- season-dated team associations through `seasons[].school` and `seasons[].year`
- team-level season history for the coach record

This is enough to represent a head-coach continuity lane at the team level if the coach record is interpreted season by season.

## What the Source Does Not Provide

The live coaching source does not visibly provide:

- an explicit head-coach role field
- offensive coordinator records
- defensive coordinator records
- staff-role labels for assistant coaches
- an explicit coaching-change event feed
- an explicit coaching-continuity score
- scheme continuity labels

## Role-Level Coverage Assessment

### Head coach

The source can support head-coach continuity at a practical level because it exposes coach identity, hire date, and season/team history.

### Offensive coordinator

The source does not visibly expose offensive coordinator role records in the observed payload.

### Defensive coordinator

The source does not visibly expose defensive coordinator role records in the observed payload.

## Season-Dated Continuity Assessment

### Season-dated records

Yes.

The `/coaches` payload includes `seasons[].year` and `seasons[].school`, which makes the source season-dated and team-associated.

### Team associations

Yes.

The payload ties each coach record back to a school/program through the nested `seasons` array.

### Coaching changes across seasons

Partially.

Head-coach continuity can be inferred by comparing season rows for a coach record, or by comparing team-year coach records across seasons.

However, the source does not visibly expose explicit coaching-change events or staff-role changes for OC/DC.

## Current Source Verdict

The current source is sufficient for a partial head-coach continuity lane, but not sufficient for a complete coaching continuity layer that includes head coach, offensive coordinator, and defensive coordinator continuity together.

## Explicit Answers

### Can HC continuity be calculated?

Yes, at least at the team level, from the live `/coaches` payload and its season-dated coach history.

### Can OC continuity be calculated?

Not from the observed live payload alone.

### Can DC continuity be calculated?

Not from the observed live payload alone.

### Is a new source required?

Yes, if the goal is a full coaching continuity artifact that includes HC, OC, and DC continuity together.

If the objective is only a head-coach continuity subset, then the current source may be sufficient.

### Can M6 proceed with the current source alone?

Not for the full M6 coaching continuity layer.

The current source can support a partial head-coach continuity artifact, but a complete canonical coaching continuity layer still needs either a richer coaching source or an additional derived/staff-history source.

## Recommended Interpretation

Use the current `/coaches` endpoint as the head-coach continuity backbone only.

Treat offensive-coordinator and defensive-coordinator continuity as blocked until a source is identified that exposes role-level staff history or can be joined from another canonical data surface.

## Remaining Blockers

- no visible OC/DC role fields in the live payload
- no visible staff-history feed in the observed source
- no explicit coaching-change event model
- no canonical local coaching artifact yet

## Conclusion

The coaching source is not empty, but it is incomplete for full M6 onboarding.

It supports head-coach continuity, season-dated team association, and season-over-season comparison at the head-coach level.

It does not yet support a full coaching continuity artifact covering head coach, offensive coordinator, and defensive coordinator without a new source or a richer source join.
