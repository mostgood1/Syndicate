# SmartSim Production Integration Plan

- Date: 2026-07-15
- Scope: design/spec only — **no SmartSim 2.0 code was modified**, and nothing in this plan has been implemented yet. This document defines how a future implementation pass should wire SmartSim 2.0 into Syndicate's NCAAF pipeline.
- References: `smartsim_integration_assessment.md`, `smartsim_ensemble_evaluation_report.md`.

## Task 1: Where the Current Projection Engine Is Consumed

Traced exactly, function by function:

```
data/ncaaf_source/data/college_football_schedule_2025_predicted_totals_enhanced*.csv
        |  (predicted_home_points, predicted_away_points, predicted_total_points, predicted_win_margin, model_home_win_prob)
        v
syndicate/features/ncaaf/cards.py
    _prediction_rows()              -- reads the newest snapshot CSV
    _prediction_weeks() / _prediction_index()   -- indexed by (week, away_team, home_team)
    _runtime_prediction_rows(week)  -- filters to one week, dedupes, requires the 3 core predicted_* fields present
        v
    _runtime_scoreboard_projection(row, week)   -- <<< THE SEAM (see below)
        -> {home_points, away_points, total_points, spread_label, win_probability, source_label, kickoff, venue}
        v
    _runtime_publication_profile(scoreboard)    -- coverage_score/tier -> publication_ready gate (A/B publish, C/D suppress)
        v
    _build_smartsim_ncaaf_card_contract(row, week, season)  -- assembles the final per-game card dict + summary text
        v
    build_smartsim_cards_page_context(selected_week)  -- assembles the full week's card list
        v
syndicate/blueprints/ncaaf.py  -- /ncaaf/cards and its API twin call build_smartsim_cards_page_context directly
```

A second consumer branches off the same data, one level up:

```
syndicate/features/ncaaf/cards.py:_runtime_prediction_rows(week)
        v  (imported directly)
syndicate/features/ncaaf/picks.py:build_betting_card_page_context(season, week)
        v
syndicate/blueprints/ncaaf.py  -- /ncaaf/season/<season>/betting-card and its API twin
```

**Implication for integration**: `_runtime_scoreboard_projection` is the single seam that both consumers (cards page and betting/picks page) inherit from. Injecting a blended projection at this one function — rather than in `_prediction_rows`, `_build_smartsim_ncaaf_card_contract`, or in the blueprint routes — reaches both UI surfaces through the existing, unmodified downstream pipeline (publication gating, card assembly, betting-card edge computation all keep working exactly as they do today).

### Critical finding: a naming collision already exists

The **current** engine's own output is already branded "SmartSim" throughout this exact code path: `source_label: "SmartSim runtime"`, `build_smartsim_cards_page_context`, `_build_smartsim_ncaaf_card_contract`, and the user-facing summary text literally reads `"SmartSim projects {home_team} {score} - {score} {away_team}..."`. This is **not** SmartSim 2.0 — it is the pre-existing engine's own product name, and it predates this project's work entirely.

This must be resolved before any blended output ships, or the UI will show a "SmartSim" number with no way for a user (or a future engineer) to tell whether it came from the legacy engine, SmartSim 2.0, or a blend of both. Recommendation: reserve "SmartSim" / "SmartSim 2.0" exclusively for the Football Core engine from this point forward, and rename the legacy engine's user-facing strings and `source_label` value (e.g., `"SmartSim runtime"` → `"Model projection"` or the legacy system's actual internal name) as a prerequisite step, before wiring anything else in this plan. This is a current-engine-side rename, not a SmartSim change, so it does not conflict with "do not modify SmartSim."

## Task 2: SmartSim Output Contract

SmartSim 2.0 itself is not modified — this contract lives entirely in new, Syndicate-side glue code that calls `simulate_game` as a library.

### In-process contract (dataclass, for the batch job described in Task "Where should SmartSim be called")

```python
@dataclass(frozen=True)
class SmartSimNcaafProjection:
    game_id: str
    season: int
    week: int
    home_team: str
    away_team: str
    home_score_mean: float          # Monte Carlo mean over N seeds
    away_score_mean: float
    margin_mean: float              # home_score_mean - away_score_mean
    total_mean: float
    margin_stdev: float             # population stdev across the N simulated margins
    total_stdev: float              # population stdev across the N simulated totals
    home_win_rate: float            # fraction of N seeds where home_score > away_score
    seeds_used: int                 # e.g. 300, matching the backtest methodology
    profile_name: str                # "ncaaf_v2" -- which CalibrationProfile was used
    rating_source: str               # e.g. "cfbd_ppa_season_2025" -- provenance of the offense/defense ratings fed in
    generated_at: str                # ISO timestamp
```

`home_win_rate` is a new field not computed in the backtest reports but directly available from the same 300-seed loop (fraction of seeds where the home team wins) — worth adding since it gives SmartSim its own native win-probability, comparable to the engine's `model_home_win_prob`.

### On-disk artifact (matches the existing CSV-artifact convention in this codebase)

`data/ncaaf_source/data/smartsim2_projections_{season}_wk{week}.csv`, one row per `SmartSimNcaafProjection`, column names matching the dataclass fields exactly. This is a **new, separate artifact** — it does not modify or extend the existing `college_football_schedule_2025_predicted_totals_enhanced*.csv` schema, so nothing about the current engine's own artifact changes.

## Task 3: Weighted Blend Implementation

New module (not yet created): `syndicate/features/ncaaf/smartsim2_blend.py`. Implements exactly the method validated as best-performing in `smartsim_ensemble_evaluation_report.md` — the fixed-weight, correlation-derived blend with SmartSim's total bias corrected — not the 50/50 average (shown clearly worse) and not the confidence-weighted variant (statistically indistinguishable from the simple weighted blend, not worth the added complexity per that report's own recommendation).

```python
# Weights derived from the 103-game backtest (smartsim_ensemble_evaluation_report.md).
# Recalibrate on a rolling schedule (see Monitoring) as more real, graded games accumulate --
# do not treat these as permanent constants.
MARGIN_WEIGHT_ENGINE = 0.395
MARGIN_WEIGHT_SMARTSIM = 0.605
TOTAL_WEIGHT_ENGINE = 0.114
TOTAL_WEIGHT_SMARTSIM = 0.886
SMARTSIM_TOTAL_BIAS = 6.11  # subtracted from smartsim_total before blending

def blend_margin(engine_margin: float, smartsim_margin: float) -> float:
    return MARGIN_WEIGHT_ENGINE * engine_margin + MARGIN_WEIGHT_SMARTSIM * smartsim_margin

def blend_total(engine_total: float, smartsim_total: float) -> float:
    corrected_smartsim_total = smartsim_total - SMARTSIM_TOTAL_BIAS
    return TOTAL_WEIGHT_ENGINE * engine_total + TOTAL_WEIGHT_SMARTSIM * corrected_smartsim_total
```

**Fallback behavior (required, not optional)**: if a `SmartSimNcaafProjection` is missing for a game (team ratings unavailable, artifact not yet generated for that week, simulation error), `_runtime_scoreboard_projection` must fall back to the engine-only value it produces today — SmartSim availability must never block or degrade the existing pipeline's baseline behavior.

## Task 4: Conditional Usage Rules

Derived directly from the segment analysis in `smartsim_ensemble_evaluation_report.md`. Thresholds below use the same tercile-style boundaries observed in that 103-game backtest; treat them as a first cut to be re-validated as sample size grows (see Monitoring).

| Situation | Detection | Margin rule | Total rule |
| --- | --- | --- | --- |
| **Toss-up game** | `\|market_margin\|` (or `\|engine_margin\|` if market unavailable) `≤ 5` | **Blend** — this is the single clearest win in the backtest (blend margin MAE 9.99 vs. engine 12.35, nearly matching the market) | Blend (bias-corrected) |
| **Large talent mismatch** | `\|market_margin\| ≥ 10` | **Engine only** — blending cost accuracy here (blend margin MAE 17.85 vs. engine 18.31 was closer than SmartSim's own 18.67, but the *side-selection* edge SmartSim showed on big favorites, 77.1% vs engine 74.3%, is worth surfacing as a secondary flag, not the headline number) | Blend (bias-corrected) — still an improvement over engine alone in this segment |
| **Conference game** | `conference_game == True` (already a column in the current engine's own artifact) | Blend | Blend |
| **Inflated-total game** | market/engine total in the top tercile of the week (empirically `≥ ~55` in the backtest) | Blend | **Consider raw SmartSim, not the bias-corrected blend** — part of SmartSim's "bias" here is genuine shootout-detection skill; the correction that helps on average slightly costs accuracy in this specific segment. Flag for further validation before hard-coding this exception. |
| **Low-total game** | bottom tercile (`≤ ~50` in the backtest) | Blend | **Blend (bias-corrected) — required.** Raw SmartSim is clearly worse here (total MAE 17.32 vs. engine 13.58); the bias correction is what recovers this segment. |
| **High-variance game** | `SmartSimNcaafProjection.margin_stdev` (or `total_stdev`) above its own rolling-median for the week | **Reduce SmartSim's blend weight** (or fall back toward engine-only) for that specific game, and surface a low-confidence flag downstream — a game where SmartSim's own 300 seeds disagree with each other widely is one SmartSim itself is uncertain about, distinct from a market-defined toss-up | Same treatment |
| **Missing/degraded input** | no team ratings resolvable, artifact not generated, simulation error | **Engine only** (hard fallback, not a "rule" so much as a requirement — see Task 3) | Engine only |

## Task 6: Explicit Answers

### Where should SmartSim be called?

**Offline, in a new scheduled batch job — not inline in a web request.** At roughly 15ms per simulated game and 300 seeds per point estimate (the Monte Carlo methodology validated in both backtest reports), one game projection costs ~4.5 seconds; a full NCAAF week (50-60 FBS-vs-FBS games) costs 4-5 minutes. That is a batch workload, not something to run synchronously inside a Flask request. Recommended shape: a new script analogous to `scripts/refresh_ncaaf_oddsapi.py`, run on the same weekly refresh cadence as the current engine's own prediction artifact, which resolves per-team ratings, calls `simulate_game` 300 times per game, and writes the `smartsim2_projections_{season}_wk{week}.csv` artifact described in Task 2. `_runtime_scoreboard_projection` (or a new sibling function called from the same seam) reads that artifact at request time — cheap, no simulation happens on the request path.

### Which outputs should be surfaced?

**Blended margin/spread (conditionally, per the rules above) and blended total (always, bias-corrected).** Optionally, SmartSim's own `home_win_rate` alongside the engine's existing `model_home_win_prob` as a second win-probability data point, since it costs nothing extra to compute from the same seed loop and the ensemble report never tested it directly — flag it as unvalidated rather than asserting it improves anything yet.

### Which outputs should remain internal?

**Raw (unblended) SmartSim home/away scores, the blend weights and bias constant, `margin_stdev`/`total_stdev`, `seeds_used`, `profile_name`, and `rating_source`.** None of these should reach the user-facing card text — showing three different projected scores (engine, raw SmartSim, blend) per game would be confusing, and raw SmartSim underperforms on side-selection/favorite-calling standalone (per the ensemble report), so surfacing it as if it were an equally-trustworthy independent prediction would be misleading. These fields belong in the artifact/logs for the monitoring described below, not the UI.

### How should blends be calculated?

Per Task 3: fixed, correlation-derived weights (margin 0.395/0.605 engine/SmartSim; total 0.114/0.886 engine/SmartSim with SmartSim's total bias-corrected first), applied conditionally per Task 4's situation table, with a hard fallback to engine-only whenever a SmartSim projection is unavailable for a game.

### What monitoring should be added?

1. **Rolling backtest job**: re-run the exact methodology from `smartsim_integration_assessment.md`/`smartsim_ensemble_evaluation_report.md` on newly-completed weeks as the season progresses (not just the two historical weeks used so far), tracking MAE/bias/correlation/side-accuracy for engine, raw SmartSim, and the production blend, per week. This is both a monitoring signal and the mechanism for the periodic weight recalibration flagged in Task 3.
2. **SmartSim availability/error rate**: what fraction of a week's games got a real `SmartSimNcaafProjection` vs. fell back to engine-only (missing ratings, simulation errors) — a silently-degrading fallback rate is the first sign something upstream (rating source, artifact generation) broke.
3. **Disagreement monitor**: fraction of games per week where engine and SmartSim disagree on side (sign of margin) beyond some magnitude — a sudden spike is either a genuine surge in toss-up/upset-prone games or a data-quality problem in one of the two inputs, and is exactly the kind of signal this plan's "high-variance game" rule depends on being trustworthy.
4. **Publication-gate impact**: does blending change the `coverage_score`/`publication_ready` outcome for a meaningful number of games (more publishable, fewer, or just different ones) versus the engine-only baseline — since `_runtime_publication_profile` currently derives its score from the scoreboard dict this plan modifies, this needs an explicit before/after check the first time blending goes live, not an assumption that it's neutral.
5. **Segment-rule validation over time**: the toss-up/mismatch/total-tercile thresholds in Task 4 came from one 103-game sample. Track blend performance broken out by the same segments every few weeks and adjust thresholds (or retire a rule) if a larger sample doesn't reproduce the original pattern.

## Open Items Not Resolved by This Plan

- **Naming collision resolution** (see Task 1) is a prerequisite, not a nice-to-have — it should land before any blended number reaches a user-facing card.
- **Production rating source**: this plan's contract assumes per-team offense/defense ratings are resolvable at generation time; the backtest sourced these from CFBD's season-long `/ppa/teams` endpoint (a mild lookahead-bias proxy, disclosed in `smartsim_integration_assessment.md`). A production job needs a **walk-forward** rating source (ratings computed only from games completed before the projected week) — this plan defines the contract's `rating_source` field to make that provenance explicit and auditable, but does not itself solve the walk-forward-ratings problem.
- **NFL is out of scope for this plan.** As established in `smartsim_integration_assessment.md`, the NFL side has no current-engine scored-projection artifact to blend against at all — that is a prerequisite gap on the current-engine side, not something this plan (or a SmartSim change) can address.
