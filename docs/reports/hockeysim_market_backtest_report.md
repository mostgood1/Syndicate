# hockeysim market-comparison backtest — the instrument NHL never had

Answers a question none of this session's other measurements answer: **does hockeysim's actual
published prediction beat the price a real market already set?** Every calibration this session ran
(special-teams multipliers, block-rate scale, the xG model's holdout AUC) checks whether the
engine's internal statistics match real AGGREGATE reality — none of it checks whether a specific
game's prediction is closer to the truth than what a sportsbook already priced. This is that check,
mirroring the exact methodology MLB's `convergence-phase7-crps` lane already validated
(`scripts/grade_mlb_hitter_props_vs_market.py`, `scripts/measure_all_inputs_effect.py`).

## Metric and why it's the right one

**Brier score** (`syndicate/features/shared/model_scoring.py::brier_score`) — `(probability −
outcome)²`, lower is better, 0.25 is a coin flip. Not CRPS: CRPS scores a continuous distribution
against a realized value (what §6's Elo backtest and `skill_census_crps.py`'s climatology check
use); this compares two probability FORECASTS — the model's and the market's — against the same
binary outcome, which is exactly what Brier is for.

## Why the model's own probability columns are not circular

`predictions_{date}.csv`'s `p_home_ml`/`p_over`/`p_home_pl_-1.5` come from
`adapters.build_game_prediction`, which only calls `game_market_sim.simulate_from_period_lambdas`
on `HockeyGameFeatures.period_goal_lambdas`. Market-anchoring (`market_anchoring.anchor_game_features`)
is a separate, opt-in mechanism that only touches the PROPS pipeline (`build_prop_projections`),
never this one — confirmed by reading `adapters.py` directly, not assumed from column naming. Where
a `_model`-suffixed column exists (one legacy file predating the Syndicate-owned migration, written
by vendor code this pass did not audit), it's preferred anyway as cheap insurance.

## Data sources — real, no synthetic substitution

- **Predictions + market odds, same row**: `data/nhl_source/data/processed/predictions_<date>.csv`
  — `home_ml_odds`/`away_ml_odds`/`over_odds`/`under_odds`/`home_pl_-1.5_odds`/`away_pl_+1.5_odds`
  are the real American prices captured at build time.
- **Settled outcomes**: `data/nhl_source/data/ingestion_cache/boxscore_*.json` — the same cache
  §2e/§2g/§2i/§2j/§2k already bulk-fetched this session (1,323 games), filtered to genuinely
  finished games (`gameState in {"OFF","FINAL"}`), joined on `(date, home_abbr, away_abbr)` via the
  same `syndicate.local_nhl_odds._team_abbr` resolver `loaders.py` already uses.

## A real bug found while building this, not after

The first run reported `home_ml:scored=8` from only 5 prediction *files*. Investigating showed 4 of
those files (`predictions_2026-06-12/13/14.csv`, `predictions_2026-07-09.csv`) are **byte-identical
duplicates** of `predictions_2026-06-11.csv` — confirmed with a plain `diff`, not assumed. The NHL
prediction pipeline was re-serving the last real slate under new date-stamped filenames after the
underlying playoff series ended, rather than genuinely having no games. Scoring these as separate
observations would have silently inflated `n` with 4 literal duplicates of one game, biasing the
average toward whichever game happened to repeat. Fixed with an explicit dedup keyed on
`(date, home_abbr, away_abbr)` (using the CSV's own `date` column, not the filename — the filename
is unreliable here) — every dropped duplicate is counted under `duplicate_stale_file_row`, not
silently discarded. **This staleness pattern is a separate, real finding about the production
pipeline, worth its own follow-up** (see "What this surfaced," below) — not something this backtest
script itself should paper over.

## Join discipline

Every row that fails to score is counted under a named reason (`no_settled_outcome`, `no_model`,
`no_market`, `push`, `devig_failed`) — nothing is silently dropped, matching
`grade_mlb_hitter_props_vs_market.py`'s own hard-won convention. `devig()` is passed both sides of
every market. A push (total exactly at the line) is excluded from scoring, not counted as a loss. A
market whose base rate falls at or outside `[0.001, 0.999]` is refused rather than reported (Brier
is degenerate there) — not triggered this run, but load-bearing at scale.

## Measured result — and why it cannot be trusted as a verdict

| market | n (after dedup) | model Brier | market Brier | verdict |
|---|---|---|---|---|
| home moneyline | 4 | 0.2630 | 0.2061 | market wins |
| total over/under | 4 | 0.2294 | 0.2115 | market wins |
| home puck line (-1.5) | 3 | 0.2146 | 0.2133 | market wins |

**Stated as plainly as every other measurement this session**: n=3–4 per market, all from one
playoff series' single-game nights, is nowhere near a sample that can support a real "beats/loses"
conclusion. The MLB harness this mirrors scores hundreds of props per market and *still* found its
single-seed noise floor (0.00326 Brier, from re-simulation variance) exceeded the effects it was
built to detect — this NHL run has no re-simulation variance to worry about (it scores fixed,
already-published predictions, not repeated sim draws), but the *sample-size* problem is worse
here, not better. **This run proves the harness is correct end-to-end on real data. It is not a
statistically powered verdict either way**, and the directionally-consistent "market wins all
three" should not be read as confirmation of anything beyond what MLB's own much larger sample
already found for a different sport's engine.

## What this surfaced, worth a follow-up

- **The stale-file duplication is a real production-pipeline finding**, not an artifact of this
  script. Something is re-writing `predictions_<date>.csv` with a copy of an earlier date's content
  instead of either genuinely regenerating it or not writing a file at all when no game exists.
  Worth tracing (likely in the daily-update wrapper or a stale-artifact fallback path) — this
  backtest only found it because it happened to check row-for-row content equality; nothing else in
  this session's audits would have caught it.
- **Local coverage is the binding constraint**, not the harness. `predictions_<date>.csv` locally
  spans only the tail of one playoff series. A real market-comparison result needs either a fuller
  regular-season mirror pulled from production, or this script re-run continuously as new dates
  accumulate. The harness itself (`scripts/grade_nhl_predictions_vs_market.py`) needs no changes to
  do that — point `--root` at a fuller `SYNDICATE_ARTIFACT_ROOT_NHL` mirror and re-run.
- **Puck line coverage is thinner than moneyline/total** (1 of 4 matched games had no puck-line
  odds) — worth checking whether that's a genuine market-availability gap or a capture gap, if this
  becomes a market worth tracking at scale.

---

## Addendum — pulled from production, the binding constraint above addressed

Per CLAUDE.md's own standing rule ("Render is the source of truth — `data/**` in git is a lossy
mirror... don't diagnose 'missing data' from the local checkout — check production first"), added
`--source production`/`both` to `scripts/grade_nhl_predictions_vs_market.py`: pulls every date
`/nhl/api/cards/dates` currently lists from `https://syndicate-an21.onrender.com` (a PUBLIC route,
no admin token needed), reshapes each game into the same row shape the scoring logic already reads,
and caches each raw response to `data/nhl_source/data/ingestion_cache/nhl_cards_<date>.json` (same
convention as the boxscore cache) so a re-run doesn't re-hit production.

**Confirmed non-circular for this route specifically**, not assumed from the earlier general
finding: `lookahead_applied=False`, `using_sample_data=False`, `hasArtifactData=True`, and
`source_path` on the payload literally points at `predictions_<date>.csv` on Render's disk — the
API is directly serving the same real, un-transformed artifact, packaged as JSON.

**Moneyline + total odds only** — American prices come from the `"Moneyline and total board"`
panel's `summary_stats` (a clean label→value lookup). Puck-line American odds are **not exposed by
this route at all**, confirmed against several dates where the puck-line EV was non-null (proving
the underlying data exists, this display layer just never surfaces the price) — `--source both`
recovers puck-line coverage from local files, deduped against production on the same
`(date, home_abbr, away_abbr)` key.

**A second real bug, found the same way as the first — by checking, not assuming**: the first
production pull showed 23 of 24 rows failing a naive `lookahead_applied` filter. Investigating
`lookahead_applied`'s actual meaning (reading `nba/cards.py`'s identical flag, then confirming
against every cached NHL response) showed it means something different than the name suggests:
**the REQUESTED date had no games (an off day) and the route served the NEXT date that does** —
`payload["date"] != payload["requested_date"]`, always later, never a live/in-game adjustment.
Rejecting those rows outright — an earlier draft of this script did exactly that — would have
silently discarded real, valid games mislabeled under the wrong date, the same *shape* of bug as
the stale-duplicate-file finding above. Fixed the same way: key every row on `payload["date"]` (the
RESOLVED date), never the date requested — the existing dedup then naturally collapses the many
off-day requests that resolve to the same underlying slate (13 collapsed in the `both` run below).

### Updated measured result

| market | n (`--source production`) | n (`--source both`) | model Brier | market Brier | verdict |
|---|---|---|---|---|---|
| home moneyline | 14 | 15 | 0.2905 | 0.2769 | market wins |
| total over/under | 14 | 15 | 0.2102 | 0.2378 | **MODEL BEATS MARKET** |
| home puck line (-1.5) | 0 (no odds via this route) | 3 | 0.2146 | 0.2133 | market wins |

Coverage widened from 4 dates (one playoff series' tail) to 12 dates with a matched settled outcome
(`2026-03-01` through `2026-06-11`) — roughly 3-4x the sample, and no longer confined to one
matchup's single-game nights.

**Stated exactly as plainly as the first result, not more confidently just because n went up**:
n=14-15 is still far below any sample that can support a real "beats/loses" verdict — the total-over
result flipping to "model beats market" on this larger-but-still-small sample is at least as
consistent with noise as with a real signal; the earlier CAVEAT about MLB's much larger sample
still finding its own noise floor exceeded the effects under study applies with MORE force here,
not less, precisely because a "beats market" headline is the exact kind of result that noise would
most readily manufacture. **This is not evidence of an edge. It is evidence the sample got bigger
and the harness held up under a real production pull.** Re-running as new NHL dates accumulate
(the season resumes in October) is the only way this graduates from "the harness works" to
"here is a measured result," and even then only after the pre-registration discipline
`docs/ai_context/mlb_edge_scan_preregistration.md` describes — not a single ad hoc pull.
