# NCAAF Phase 2.5 Feature-Aware Evaluation Report

## What changed
This phase turns NCAAF artifact completeness into an operational signal. The pipeline now computes a shared `coverage_score`, `coverage_tier`, `coverage_warnings`, and `publication_status` from the runtime feature coverage already attached to NCAAF candidates.

The coverage profile is derived from four artifact families:
- roster coverage
- transfer coverage
- returning production coverage
- coach continuity coverage

The model outputs themselves were not changed. The football model calculations remain intact; coverage only affects downstream confidence handling, ranking tie-breaks, and publication metadata.

## Contract trace
The affected seam is:
`candidate -> evaluation -> confidence -> ranking -> publication`

The implementation now does the following:
- preserves `feature_coverage` on NCAAF candidates and recommendations
- computes a shared coverage profile from the attached artifact coverage map
- stores `coverage_score`, `coverage_tier`, `coverage_warnings`, `coverage_components`, `publication_ready`, `publication_status`, and `coverage_adjusted_confidence`
- uses the adjusted coverage confidence in the response/publication surfaces while preserving the original model confidence as `model_confidence`
- applies coverage as a ranking tie-breaker only
- exposes the new fields on board cards and response payloads
- records a coverage summary in the evaluation bundle

## Publication tiers
The operational publication policy is:
- `A`: `coverage_score >= 0.90`, publishable
- `B`: `coverage_score >= 0.75`, publishable
- `C`: `coverage_score >= 0.50`, suppressed
- `D`: `coverage_score < 0.50`, suppressed

The current implementation treats `A` and `B` as publishable and `C`/`D` as suppressed.

## Confidence behavior
Coverage now influences confidence in a backward-compatible way:
- `model_confidence` preserves the original model result
- `confidence` is replaced with the coverage-adjusted value for publication-facing payloads
- the adjusted value is bounded so it remains in a valid probability range

This keeps the model math untouched while making publication behavior sensitive to artifact completeness.

## Validation
Validation completed successfully:
- `get_errors` passed for the touched files
- direct helper probes confirmed the coverage profile outputs the expected tiers and publish/suppress behavior

Representative helper results:
- full coverage -> `coverage_score=1.0`, `coverage_tier=A`, `publication_status=publishable`
- partial coverage -> `coverage_tier=C`, `publication_status=suppressed`

## Week 1 demonstration
I attempted to run the live NCAAF query path for a Week 1 demonstration, but the request chain is currently blocked by an unrelated WNBA `NameError` in `syndicate/features/wnba/cards.py` (`_finalize_home_prop_rows` is undefined). Because of that upstream error, I did not fabricate a live Week 1 payload.

The report therefore captures the implemented contract and validation results, but the runtime Week 1 demonstration still needs a clean request path after that unrelated WNBA issue is fixed.

## Files touched
- [syndicate/features/shared/intelligence_evaluation.py](syndicate/features/shared/intelligence_evaluation.py)
- [syndicate/features/intelligence.py](syndicate/features/intelligence.py)
- [syndicate/features/shared/recommendation_engine.py](syndicate/features/shared/recommendation_engine.py)
- [syndicate/features/intelligence/api/response_builder.py](syndicate/features/intelligence/api/response_builder.py)
- [syndicate/features/intelligence_board.py](syndicate/features/intelligence_board.py)

## Notes
This change intentionally avoids modifying football model calculations. It makes artifact completeness operational by carrying coverage into evaluation, confidence, ranking, and publication decisions.