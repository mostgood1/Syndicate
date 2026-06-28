# Intelligence / Betting Board Pipeline Gap Audit

This document is a read-only audit of the intelligence + betting board pipeline across MLB, NBA, WNBA, NFL, NHL, NCAAB, and NCAAF.

Scope:
- data availability
- ingestion into intelligence
- candidate generation completeness
- opportunity generation consistency
- board shaping and contract behavior
- cross-sport parity and alignment

This audit does not change behavior. It documents the current code paths and the gaps that matter for targeted fixes.

## Owning surfaces

- Core orchestration: [syndicate/features/intelligence.py](../syndicate/features/intelligence.py)
- Analysis views: [syndicate/features/intelligence_analysis_views.py](../syndicate/features/intelligence_analysis_views.py)
- Reasoning / brief shaping: [syndicate/features/intelligence_reasoning.py](../syndicate/features/intelligence_reasoning.py)
- Evaluation metadata: [syndicate/features/shared/intelligence_evaluation.py](../syndicate/features/shared/intelligence_evaluation.py)
- Board contract: [syndicate/features/intelligence_board.py](../syndicate/features/intelligence_board.py)

Relevant shared control points in the core orchestrator:
- overview and status assembly: [build_intelligence_overview](../syndicate/features/intelligence.py#L2342)
- odds-history ingestion: [_load_odds_history_payload_for_sport](../syndicate/features/intelligence.py#L2510)
- advanced-input resolution: [_advanced_input_specs_for_sport](../syndicate/features/intelligence.py#L3124)
- candidate collection: [_collect_candidates](../syndicate/features/intelligence.py#L4425)
- MLB artifact backfill: [_mlb_home_run_candidates_from_artifact](../syndicate/features/intelligence.py#L3470) and [_mlb_market_prop_candidates_from_artifact](../syndicate/features/intelligence.py#L3661)
- live-state guard: [_apply_live_state_context_to_candidates](../syndicate/features/intelligence.py#L3915)
- market filter: [_filter_candidates_to_requested_markets](../syndicate/features/intelligence.py#L4006)
- board shaping: [_build_board_dictionary](../syndicate/features/intelligence.py#L6338)
- query entrypoint: [run_intelligence_query](../syndicate/features/intelligence.py#L6381)

## Per-sport audit

### MLB

**Data Sources**
- artifacts path: `data/mlb_source` and `data/mlb_source/source_artifacts` via [syndicate/features/mlb/sources.py](../syndicate/features/mlb/sources.py)
- sim outputs path: `data/daily/sims/<date>` and season eval / betting-day artifacts via [syndicate/features/mlb/sources.py](../syndicate/features/mlb/sources.py)
- odds path: daily snapshot game lines / hitter props / pitcher props plus odds refresh history via [syndicate/features/mlb/sources.py](../syndicate/features/mlb/sources.py)
- live inputs path: live lens report / log plus raw feed live paths via [syndicate/features/mlb/sources.py](../syndicate/features/mlb/sources.py)
- missing or inconsistent paths: none at the source-layer breadth level, but MLB has the most path complexity and therefore the highest risk of branch-specific drift

**Ingestion**
- artifact loader: [_load_odds_history_payload_for_sport](../syndicate/features/intelligence.py#L2510), MLB-specific artifact helpers, and status readiness paths
- odds loader: daily snapshot odds readers plus odds-history payload matching
- live loader: [_apply_live_state_context_to_candidates](../syndicate/features/intelligence.py#L3915) and MLB live-state helpers
- fallback behavior: reconcile-copy from source artifacts, HR-target backfill, top-props backfill, and live-state adjustment before ranking
- path mismatches or risks: the breadth is strong, but the number of alternate paths makes it easiest for a single branch to diverge from the rest

**Candidates**
- source of candidates: home rails, dashboard games, MLB HR target artifacts, and MLB top-props artifact rows
- includes all games? YES, if dashboard games are present
- includes props? YES
- includes live markets? YES
- early filtering or truncation: state guard, requested-market filter, and dedupe after scoring

**Opportunities**
- evaluation inputs: advanced inputs, odds history, simulation, MLB Statcast profile, and live-state context
- filtering points: final-state exclusion, stale pitcher exclusion, requested markets, and dedupe
- reasons candidates may be dropped: final/settled state, stale pitcher state, missing market match, or duplicate identity
- inconsistencies vs other sports: MLB is the only sport with explicit odds-history matching plus artifact-driven prop backfill

**Board**
- appears on board? YES
- lane behavior: shared live / pregame / archived behavior through the board contract
- handling of empty results: hidden if no recommendations survive scoring and filtering
- fallback overriding sport-specific logic: only through the generic analysis fallback, not through MLB-specific board shaping

### NBA

**Data Sources**
- artifacts path: the preferred NBA source root and `data/processed` via [syndicate/features/nba/sources.py](../syndicate/features/nba/sources.py)
- sim outputs path: processed recommendations and season betting-card artifacts via [syndicate/features/nba/sources.py](../syndicate/features/nba/sources.py)
- odds path: indirect through processed recommendation and props artifacts, not a dedicated odds snapshot reader
- live inputs path: `data/processed/live_snapshots` via [syndicate/features/nba/sources.py](../syndicate/features/nba/sources.py)
- missing or inconsistent paths: path resolution can silently prefer one configured root over another; there is no explicit odds module here

**Ingestion**
- artifact loader: processed_path and live_snapshot_path in [syndicate/features/nba/sources.py](../syndicate/features/nba/sources.py)
- odds loader: indirect only; the source module does not expose a dedicated odds snapshot reader
- live loader: NBA live context paths in [syndicate/features/intelligence.py](../syndicate/features/intelligence.py)
- fallback behavior: first-existing path selection plus dated-fallback resolution
- path mismatches or risks: stale-root selection and no explicit odds ingestion contract

**Candidates**
- source of candidates: home rails plus dashboard games
- includes all games? YES, if dashboard games are complete
- includes props? YES
- includes live markets? YES
- early filtering or truncation: state guard, requested-market filter, and dedupe

**Opportunities**
- evaluation inputs: team advanced stats, live play-by-play, props predictions, and live state
- filtering points: NBA analysis view gating, market fit, and live-state context
- reasons candidates may be dropped: missing advanced inputs, stale live state, or market mismatch
- inconsistencies vs other sports: NBA has rich inputs, but no dedicated odds snapshot loader

**Board**
- appears on board? YES
- lane behavior: shared board lanes
- handling of empty results: hidden
- fallback overriding sport-specific logic: only the shared market-board fallback can supersede sport-specific analysis

### WNBA

**Data Sources**
- artifacts path: the preferred WNBA source root and `data/processed` via [syndicate/features/wnba/sources.py](../syndicate/features/wnba/sources.py)
- sim outputs path: processed recommendations, props, and season-card artifacts via [syndicate/features/wnba/sources.py](../syndicate/features/wnba/sources.py)
- odds path: indirect through processed recommendation and props artifacts, not a dedicated odds snapshot reader
- live inputs path: `data/processed/live_snapshots` via [syndicate/features/wnba/sources.py](../syndicate/features/wnba/sources.py)
- missing or inconsistent paths: dated fallback selection can hide which root actually supplied the payload

**Ingestion**
- artifact loader: processed_path and live_snapshot_path in [syndicate/features/wnba/sources.py](../syndicate/features/wnba/sources.py)
- odds loader: indirect only
- live loader: WNBA live context helpers in [syndicate/features/intelligence.py](../syndicate/features/intelligence.py)
- fallback behavior: best-existing dated file selection and dated fallback scan
- path mismatches or risks: stale snapshot selection and no dedicated odds ingestion contract

**Candidates**
- source of candidates: home rails plus dashboard games
- includes all games? YES, if dashboard games are complete
- includes props? YES
- includes live markets? YES
- early filtering or truncation: state guard, requested-market filter, and dedupe

**Opportunities**
- evaluation inputs: team environment, live PBP recap, player prop outputs, and live state
- filtering points: WNBA analysis view gating, market fit, and live-state context
- reasons candidates may be dropped: missing advanced inputs, stale live state, or market mismatch
- inconsistencies vs other sports: WNBA is closer to NBA than to MLB, but still lacks a source-level odds reader

**Board**
- appears on board? YES
- lane behavior: shared board lanes
- handling of empty results: hidden
- fallback overriding sport-specific logic: only through the shared analysis fallback chain

### NFL

**Data Sources**
- artifacts path: the first preferred NFL source root via [syndicate/features/nfl/sources.py](../syndicate/features/nfl/sources.py)
- sim outputs path: weekly recommendation CSVs via [syndicate/features/nfl/sources.py](../syndicate/features/nfl/sources.py)
- odds path: current-week and upcoming recommendation CSVs
- live inputs path: no explicit live-snapshot loader in the source module
- missing or inconsistent paths: the source surface is much thinner than the basketball or MLB paths

**Ingestion**
- artifact loader: recommendation_path and tracked_week in [syndicate/features/nfl/sources.py](../syndicate/features/nfl/sources.py)
- odds loader: week summaries and current-week detection
- live loader: none in the source module
- fallback behavior: publish CSV when full CSV is missing
- path mismatches or risks: no live ingestion path and no broader reconcile layer

**Candidates**
- source of candidates: home rails plus dashboard games
- includes all games? YES only if dashboard games are present
- includes props? YES
- includes live markets? YES only if home rails emit them
- early filtering or truncation: state guard, requested-market filter, and dedupe

**Opportunities**
- evaluation inputs: current week, weekly recommendations, and player props mirror context
- filtering points: football analysis gating and generic market fit
- reasons candidates may be dropped: missing current-week state, stale publish state, or market mismatch
- inconsistencies vs other sports: NFL has no live snapshot ingestion path at all

**Board**
- appears on board? YES
- lane behavior: shared board lanes
- handling of empty results: hidden
- fallback overriding sport-specific logic: the generic market-board fallback can override the football-specific path for mixed asks

### NHL

**Data Sources**
- artifacts path: the first preferred NHL source root plus artifact roots via [syndicate/features/nhl/sources.py](../syndicate/features/nhl/sources.py)
- sim outputs path: processed recommendation files via [syndicate/features/nhl/sources.py](../syndicate/features/nhl/sources.py)
- odds path: scoreboard snapshot, team odds snapshot, and props lines snapshot
- live inputs path: the same scoreboard / odds / props snapshot family
- missing or inconsistent paths: `_data_roots` uses only the first source root, so the module is narrower than MLB/NBA/WNBA

**Ingestion**
- artifact loader: recommendation_path plus processed-path helpers
- odds loader: scoreboard/team odds/props lines snapshots
- live loader: NHL context helpers in [syndicate/features/intelligence.py](../syndicate/features/intelligence.py)
- fallback behavior: first-existing candidate path selection, with no broader mirror reconciliation layer
- path mismatches or risks: root bias and thinner fallback breadth

**Candidates**
- source of candidates: home rails plus dashboard games
- includes all games? YES if dashboard games are present
- includes props? YES
- includes live markets? YES
- early filtering or truncation: state guard, requested-market filter, and dedupe

**Opportunities**
- evaluation inputs: game recommendations, shift/on-ice sequence recap, props recommendations, and scoreboard context
- filtering points: hockey prop analysis gating and generic market fit
- reasons candidates may be dropped: missing advanced inputs or market mismatch
- inconsistencies vs other sports: NHL has an explicit odds/live surface, but weaker root resilience than MLB and the basketball family

**Board**
- appears on board? YES
- lane behavior: shared board lanes
- handling of empty results: hidden
- fallback overriding sport-specific logic: only through the shared analysis fallback chain

### NCAAB

**Data Sources**
- artifacts path: the first NCAAB source root and mirror JSON under `api`
- sim outputs path: mirrored recommendations and live-state/live-lines JSON
- odds path: mirror-based recommendations and results payloads
- live inputs path: `api/live_state` and `api/live_lines`
- missing or inconsistent paths: mirror-only design means missing files become explicit local_mirror errors rather than alternate-source reads

**Ingestion**
- artifact loader: `_load_mirror_json` plus recommendations / results payloads
- odds loader: mirror-based recommendations, not a dedicated odds history layer
- live loader: `live_state_payload` and `live_lines_payload`
- fallback behavior: explicit local_mirror error payloads if mirror JSON is absent
- path mismatches or risks: mirror dependency and no alternate recovery path

**Candidates**
- source of candidates: home rails plus dashboard games
- includes all games? YES only if the mirror-backed overview is complete
- includes props? YES
- includes live markets? YES
- early filtering or truncation: state guard, requested-market filter, and dedupe

**Opportunities**
- evaluation inputs: mirrored recommendations, live state, live lines, and play-by-play derived live recap
- filtering points: NCAAB analysis view gating and generic market fit
- reasons candidates may be dropped: missing mirror payloads or market mismatch
- inconsistencies vs other sports: NCAAB is mirror-only at the source layer and has no alternate live/odds recovery path

**Board**
- appears on board? YES
- lane behavior: shared board lanes
- handling of empty results: hidden
- fallback overriding sport-specific logic: the generic market-board fallback can fill mixed asks if the sport-specific path does not resolve

### NCAAF

**Data Sources**
- artifacts path: the source root plus `data/recommendations_summary` and enhanced totals exports
- sim outputs path: weekly summary index and week summary files
- odds path: weekly recommendation summaries rather than a dedicated odds snapshot reader
- live inputs path: no explicit live-snapshot loader in the source module
- missing or inconsistent paths: NCAAF has the weakest sport-native analysis surface of the group

**Ingestion**
- artifact loader: `load_summary_index`, `week_summaries`, and `summary_path`
- odds loader: summary-driven weekly recommendation context
- live loader: none in the source module
- fallback behavior: week and season inference from the summary index
- path mismatches or risks: no live loader, no sport-specific analysis module, and weak board parity

**Candidates**
- source of candidates: home rails plus dashboard games
- includes all games? YES only if the overview emits them
- includes props? YES when home rails provide them
- includes live markets? YES only indirectly
- early filtering or truncation: state guard, requested-market filter, and dedupe

**Opportunities**
- evaluation inputs: weekly summary context, summary index, and enhanced totals
- filtering points: football analysis gating and generic market fit
- reasons candidates may be dropped: missing summary coverage or market mismatch
- inconsistencies vs other sports: NCAAF is grouped into the NFL football analysis surface and has no dedicated analysis module

**Board**
- appears on board? YES if recommendations survive generic filtering
- lane behavior: shared board lanes
- handling of empty results: hidden
- fallback overriding sport-specific logic: the generic football analysis path merges NCAAF with NFL rather than preserving a separate NCAAF lane

## Gap matrix

Legend:
- `OK` means the code path is explicit and reasonably complete for this layer.
- `PARTIAL` means the path exists but is indirect, thin, or fallback-driven.
- `GAP` means the layer is missing or structurally weak.

| Sport | Data availability | Ingestion into intelligence | Candidate generation | Opportunity generation | Board shaping / contract | Parity note |
| --- | --- | --- | --- | --- | --- | --- |
| MLB | OK | OK | OK | OK | OK | Most complete, but most complex |
| NBA | OK | PARTIAL | OK | OK | OK | Strong inputs, no dedicated odds reader |
| WNBA | OK | PARTIAL | OK | OK | OK | Similar to NBA, still odds-indirect |
| NFL | PARTIAL | PARTIAL | OK | PARTIAL | OK | Thinnest source surface, no live loader |
| NHL | OK | PARTIAL | OK | OK | OK | Explicit odds/live surface, thinner root resilience |
| NCAAB | PARTIAL | PARTIAL | PARTIAL | PARTIAL | OK | Mirror-only source contract |
| NCAAF | GAP | PARTIAL | PARTIAL | PARTIAL | PARTIAL | No sport-native analysis module |

## Cross-sport inconsistencies

### Ingestion differences

- MLB has the broadest loader graph and the most fallback branches.
- NBA and WNBA use processed and live snapshot helpers, but no direct odds snapshot reader.
- NFL is summary-driven and has no live snapshot loader.
- NHL has explicit odds/live snapshots but only the first data root is used for `data`.
- NCAAB is mirror-only and returns explicit error payloads when mirror JSON is missing.
- NCAAF is summary-driven and lacks a live loader or dedicated analysis module.

### Candidate-generation differences

- The shared collector starts from home rails plus dashboard games for every sport.
- MLB is the only sport with artifact backfill for HR targets and top props.
- NFL and NCAAF are coupled inside one football analysis lane.
- NCAAF has no sport-owned analysis module, so it cannot own its own candidate presentation path.

### Evaluation differences

- MLB gets odds-history matching plus Statcast-aware enrichment.
- NBA, WNBA, and NCAAB rely on the advanced-input bundle and simulation scoring, but with different feature depth.
- NFL and NCAAF depend on weekly summaries and recommendation context.
- NHL depends on scoreboard, odds, and shift context.
- NCAAB is the most mirror-dependent evaluation path.

### Board differences

- The board contract is global and lane-based, not sport-specific.
- Empty results are hidden rather than explicitly surfaced per sport.
- The generic `market_board` fallback can override sport-specific analysis for mixed asks.
- NCAAF is the clearest parity gap because it shares the football analysis path instead of having its own board shape.

## Top issues ranked by impact

1. NCAAF lacks a dedicated intelligence analysis module, so it cannot present a sport-native board shape and is folded into the shared football lane.
2. MLB is the only sport with fully explicit artifact backfill and odds-history matching, which makes cross-sport opportunity ranking inconsistent by construction.
3. NCAAB is mirror-only at the source layer, so missing files become hard gaps instead of falling back to alternate ingestion paths.
4. NFL has no live snapshot ingestion path in its source module, so its intelligence surface is structurally thinner than the other major sports.
5. The shared board contract hides empty results, which can make a missing or broken sport look like a quiet no-op instead of an obvious gap.

## Practical reading

If the goal is targeted fixes, this audit says the highest-value work is not a rewrite. It is:

1. close the NCAAF parity hole with a sport-native analysis surface
2. decide whether NFL should gain a true live ingestion path or stay summary-only by design
3. narrow the NCAAB mirror-only dependency if alternate source recovery is available
4. decide whether NBA/WNBA/NHL should gain explicit odds readers instead of indirect processed-artifact reliance
5. make empty-state visibility less silent at the shared board layer
