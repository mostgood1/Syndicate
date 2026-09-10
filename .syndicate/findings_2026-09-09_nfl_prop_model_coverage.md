# FINDINGS — NFL model coverage: the sim's answer was published, current, and read by nobody on the board path

`[2026-09-09, lane nfl-prop-model-coverage. Diagnosis + fix + a local end-to-end reading. Production reading owed.]`

## Why NFL was the target

`portfolio_commit`'s `PLAN_WRITTEN`, 2026-09-10T00:11:12Z:

    rows_in=3029  sized=25  positions=22  staked=$98.66
    no_model_edge_pct      1872   61.8% of the funnel
    no_model_edge_by_sport {'nfl': 1503, 'mlb': 285, 'soccer': 84}
    top_market_per_refusal {'no_model_edge_pct': 'receiving yards:473'}

**NFL is 80% of the largest refusal term**, which is itself two orders of
magnitude larger than every dark-stage effect scored in
`findings_2026-09-09_dark_stages_scored.md`. That file's conclusion was "the
platform stakes $98.66 because of MODEL COVERAGE, not because five stages are
dark". This is that conclusion acted on.

## The cause — a writer seam, for the fifth time

`nfl_prop_projections_2026_wk1.json` is **published, allowlisted
(`artifact_publisher.py:246`) and CURRENT**: 476,295 B, rebuilt
2026-09-10T00:09:04Z — **two minutes before the board build above** — carrying
**1,140 rows across 9 markets, 16 games, 249 players**, with `receiving_yards`
its LARGEST family at 327 rows. The exact market the counter names.

**Nothing on the board path read it.** `nfl_props_rows_for_week` had exactly one
consumer, `nfl/cards.py:863` (the game-card UI), and `attach_nfl_game_projections`
skips prop rows at its second line (`nfl_game_projections.py:361`). Computed,
published, discarded at the seam — the same shape as the football `quarter_log`,
the MLB inning vectors, the Kalshi liquidity fields and both codes' quarter
linescores.

## It is a JOIN, not a model

`sim_projection` **is already a cover probability, not a mean**: `props.py:635`
computes it through `_nfl_prop_model_probability` (a validated Normal/log-normal
blend) and `:645` writes it beside `projected_value`, the mean. Only the
de-vigged market fair was missing, and `_attach_sim_probability_edge` already
computes that — reused rather than hand-rolled into a sixth copy of one de-vig.

## A STALE DOCSTRING IS WHAT MADE THIS LOOK IMPOSSIBLE

`_nfl_card_prop_projection_index` states the artifact "has no line field and
several rows share a market key with different lines, so a `sim_projection`
cannot be attributed to the line a card happens to show." **True until
2026-09-08.** `_nfl_prop_join_market_key` added the line that day *precisely
because* omitting it was "a live scoring bug rather than a tidiness problem"
(371 of 371 multi-line groups showing one probability). The artifact proves it:

    receiving_yards::aj barner::24.5 -> 0.5565
    receiving_yards::aj barner::25.5 -> 0.5368
    receiving_yards::aj barner::27.5 -> 0.4978

The cards' two-segment collapse stays correct for what cards render; only the
stated REASON is out of date. **A docstring that outlived its fact closed off a
capability nobody re-checked.**

## THE REACHABILITY RUN CAUGHT A REAL BUG IN MY OWN FIX

Run end to end against the real published artifact, the first version stamped
**ZERO rows** and reported `artifact_season=2025`. `latest_season()` answers
**2025** on 2026-09-09 because it derives from `week_summaries()`, which globs
the **SmartSim2** family, not props — so early in a season it lags a year. My
fallback scan probed only `[resolved, resolved-1]` and could therefore never
reach 2026. The season the DATE names now leads the candidate list (January maps
to the previous season), and the index reports `resolution="artifact_scan"` so a
fallback never reads as a clean primary resolution.

**`model_engine_standard.md`'s "reachability before correctness" rule is the only
reason this was caught before deploy.** 13 unit tests were green while the join
was completely inert against real data.

## Measured, local, real artifact against 1,422 real served NFL prop rows

| | |
|---|--:|
| prop rows considered | 1,422 |
| **stamped with a projection** | **1,019 (71.7%)** |
| unmatched (line quoted after build, or unrated player) | 375 |
| unsupported market (raw OddsAPI key) | 28 |
| missing probability | 0 |
| of stamped, carrying a numeric `edge_vs_market_pct` | 950 (93.2%) |
| of those, `\|edge\| > _MODEL_EDGE_MAX_POINTS=15` — **dropped** by `_model_edge_for` | 224 |

So **~726 NFL rows should gain a usable `model_edge_pct`** against the 1,503
currently refused. Edge median **−0.19 pts**, range −46.80..+44.42.

**LIMITS, because the denominator is the finding.** (1) Served rows drop
`consensus`/`sides`, so the fair was reconstructed by pairing the board's own
over/under best prices — the grid carries a genuine per-side consensus, so the
950 figure is INDICATIVE, not exact. (2) **refresh-worker's own copy has 980
rows, not 1,140** (`REPAIR_SKIPPED_LOCAL_OK local_rows=980`, and
`[nfl_props] JOIN ... sim_source=artifact sim_rows=980` at 01:42Z), so live
coverage will run below 71.7%. (3) One slate, week 1, all rows
`nfl_prior_season_fallback` — correct for week 1 and visible in the stamped
provenance rather than inferred.

## The 28 unsupported rows are REPORTED, not aliased

24 arrive as `player_receptions` and 4 as `player_pass_tds` — raw OddsAPI keys —
against 1,394 carrying the display label `_NFL_PROP_MARKET_TO_STAT` expects. An
alias map would hide which producer emits the wrong shape, so they are counted
under a named reason with the offending labels in the payload.

## Owed

- **The production reading.** `prop_coverage` in the NFL coverage payload, and
  `no_model_edge_by_sport['nfl']` in the next `PLAN_WRITTEN` after the deploy.
  Until that is read, this is a local result only.
- `_nfl_card_prop_projection_index`'s docstring should be corrected where it
  stands; this file records the correction but does not edit `nfl/props.py`.
