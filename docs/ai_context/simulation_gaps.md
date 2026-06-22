# Simulation Gaps

This note is the working evaluation of where the daily-update execution path still underuses available data in the sim engine.

## MLB

MLB has the deepest artifact stack, but the daily-update path still behaves more like an artifact aggregator than a normalized simulation feed.

What daily update already produces:

- daily summary artifacts
- live-lens reports
- betting-game recommendation rows
- daily sim rows
- actual result rows
- segment and first-inning style outputs

Where the data is still underused:

- live-lens state is used mostly as a merge/fallback layer, not as a first-class simulation input contract
- segment and first-inning context are still treated more like board decoration than explicit adapter features
- actual-result rows are present for calibration, but they are not yet feeding a shared evaluation-aware adapter rule set
- recommendation metadata exists, but the engine path still does not consume it through one normalized `game_context`

Daily-update implication:

- the MLB job is producing rich enough artifacts to support a true simulation adapter, but the runtime contract still lets display shaping and source shaping blur together

## WNBA

WNBA is closer to the target state than most sports because it already has processed cards, smart-sim indexes, live snapshots, player lens, live lines, and play-by-play state.

What daily update already produces or preserves:

- processed WNBA artifacts
- smart-sim indexes and merged sim detail
- live snapshot state
- live player boxscore and player lens data
- live lines and play-by-play slices
- props and betting-card surfaces

Where the data is still underused:

- current-day precedence is still more complex than it should be, so stale processed artifacts can survive longer than they should before the live scoreboard wins
- live lines and live player context are available, but they are not yet consistently collapsed into one simulation-ready slate input
- evaluation history is still not a first-class adapter feature, so confidence shaping remains weaker than the available data would allow
- source cards now preserve richer sim payload fields, but the sim engine itself still needs the same explicit source-mode and freshness contract that the board already wants

Daily-update implication:

- WNBA is the clearest proof that preserving rich artifacts is necessary but not sufficient; the daily job still needs a tighter source-selection rule so simulation meaning does not drift between source cards, live state, and props routes

## NBA/WNBA

- partial live + simulation hybrid
- strong opportunity to unify current-day precedence rules and evaluation feedback

## NHL/NFL/NCA*
- snapshot-based, minimal simulation integration

## Global Problem
- simulation engine exists but is not consistently used

## Daily Update Execution Gaps

The daily-update execution path is where the sim engine still loses the most value.

1. There is no fully normalized cross-sport simulation input contract yet, so MLB and WNBA still enter the engine through different source shapes.
2. Current-day source selection is explicit in some routes, but not yet reported consistently in the simulation payloads that would make daily-update runs auditable.
3. Evaluation and calibration signals are present in the repository, but they are not yet consistently fed back into adapter scoring rules.
4. Display enrichment can still obscure whether a field was used for simulation or only for board rendering.

## Highest-Value Fixes

1. Build one normalized simulation input contract for MLB and WNBA first, then extend it to the rest of the board.
2. Record source mode, freshness, and source paths in the payload that reaches the sim engine.
3. Keep live-state supplements, market enrichment, and presentation-only fields separate from simulation inputs.
4. Feed evaluation and calibration history into the adapter layer so confidence and fallback choice improve over time.
5. Add parity tests that prove the daily-update job is selecting the richest available source for the requested slate.