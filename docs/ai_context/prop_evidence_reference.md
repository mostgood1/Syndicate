# Ask the Syndicate — player-prop evidence (`prop_evidence_v1`)

What a board-row player prop answers with, per sport, and where every number
comes from. Written to `docs/ai_context/model_engine_standard.md`'s rule: a
documented pipeline trace, file:line at each hop, and a gating checklist that
crosses CONSUMED against POPULATED.

Lane `prop-evidence-parity`, 2026-09-17. Every count below was measured against
production (web disk via `/api/ops/artifacts/export`, board rows via
`/api/board/layer2-shortlist`, answers via `/api/syndicate/query`) that day.

## The contract

`syndicate/features/shared/prop_evidence/contract.py`

Seven layers, always all seven, in render order:

| layer | what it answers |
|---|---|
| `player_sim` | the model's view of THIS player and stat: mean, spread, P(over the line), distribution |
| `recent_form` | last-N actual games, and the hit rate against the ROW's line and side |
| `matchup` | this opponent: head-to-head history, opposing unit/defence |
| `advanced` | usage underneath the projection: minutes, shares, per-90 rates, role |
| `game_sim` | the game the prop lives in: win prob, scoring, totals |
| `environment` | pace, rest, venue, weather, injuries, market anchor |
| `track_record` | graded record of this market for this sport, and the model-skill note |

A layer is `filled` or carries an absent reason whose prefix is one of
`no_producer`, `not_published`, `artifact_missing`, `player_not_found`,
`not_applicable`, `insufficient_sample`, `provider_error`, `not_shown`. The
reasons reach the user as the last table, "What this answer could not show".

`PropEvidence.__post_init__` marks any layer a provider forgot as
`no_producer:undeclared`, which the checklist fails on — a provider cannot
shorten an answer silently.

## Routing

`syndicate/blueprints/ask_the_syndicate_data.py:collect_focused_evidence`

* board row is a PLAYER PROP and the sport has a provider → the provider alone
  builds the answer. If it fills nothing but the track record, the old fetchers
  run too, so a join miss never answers with less than before.
* sport is MLB → the reference fetchers, unchanged, their tables tagged by title
  (`_LEGACY_TITLE_LAYERS`), plus the shared track-record layer.
* anything else (game rows, typed questions) → unchanged behaviour.

`syndicate/blueprints/ask_the_syndicate.py` serves the coverage block as
`response.prop_evidence`.

## Per-sport trace

Roots: both `<sport>_source/source_artifacts/data/...` and
`<sport>_source/data/...` are tried (`common.sport_roots`); soccer uses
`preferred_artifact_roots` because its layout is `<league>/api/...`.

### MLB — the reference (unchanged tables)

`ask_the_syndicate_data.py` `_mlb_focused_evidence:432`, `_mlb_bvp_evidence:1698`,
`_mlb_player_history_evidence:2213`, `_mlb_accuracy_evidence:2535`.
Reads `daily/daily_summary_<date>.json` (+ `_hr_targets`), `daily/snapshots/*`,
`processed/mlb_{batter,pitcher}_game_log.csv`, `statcast/features/player_features_latest.json`,
and the BvP index below. Track record from the model scorecard.

**BvP moved off web.** `scripts/build_mlb_bvp_index.py` sums per-(pitcher,
batter) plate appearances from refresh-worker's own raw Statcast chunks
(`statcast/raw_pitches/**/statcast_*.csv.gz`) plus the git-tracked legacy daily
index for dates the chunks do not cover, and writes 64 shards
`statcast/bvp/bvp_pairs_NN.json` (pitcher_id % 64). Built and published by the
weekly job `scripts/refresh_mlb_statcast_features.py` (`build_bvp_index`, and a
missing index counts as stale so the first build is not a week away).
Web reads one shard (`_bvp_index_shard`), and the table title states the index's
own `through` date, not the answer's date.
Measured: legacy = 47 files / 72.85 MB / 1,158 dates / 2021-03-15..**2026-05-11** /
384,382 pairs; shards = 91–269 KB each, 10.45 MB total; counts identical to the
old aggregation for three real pitchers. Before: 16.8 s / 17.1 s / 26.0 s Asks.

### WNBA and NBA — `prop_evidence/basketball.py`

| layer | source |
|---|---|
| player_sim | `processed/cards_sim_detail_<date>.json` → `prop_distributions[stat].distribution` (100 draws) → exact P(over); `min_mean`; combos (pr/pa/ra) from `processed/props_recommendations_<date>.csv` `model`, mean only |
| recent_form | `processed/boxscores_history.csv` **plus** dated `processed/boxscores_<date>.csv` (history stalls: newest 2026-06-30 vs dated 2026-08-25); DNPs excluded; staleness stated |
| matchup | same box files filtered to the opponent; `processed/team_advanced_stats_<season>.csv` (def rating, pace, league rank) |
| advanced | `min_mean`, actual minutes, share of team sim stat, per-36, game-script scenarios |
| game_sim | `processed/smart_sim_<date>_<HOME>_<AWAY>.json` `score` |
| environment | same file's `context` (pace, b2b, injuries out, roster mode) + `sim.injuries` + `market_anchor` |
| track_record | model scorecard (WNBA/NBA not graded yet → `insufficient_sample`) |

Joint markets (double/triple double) declare `no_producer`: the sim publishes
per-stat marginals only. NBA has no slate until October and its
`boxscores_history.csv` is not on web.

### NHL — `prop_evidence/nhl.py`

`processed/props_recommendations_<date>.csv` (`proj_lambda`, `p_over`), which is
**Poisson on the mean** (`scripts/build_nhl_artifacts.py:205`) and labelled as
the producer's pricing assumption; `processed/player_rates_latest.csv`,
`processed/lineups_<date>.csv` (line slot, PP unit, `proj_toi`),
`processed/team_xg_latest.csv`, `processed/predictions_<date>.csv`, and
`raw/player_game_stats.csv` for form. Header-only files are skipped and named;
a slate whose λ is identical for every player is flagged degenerate. Saves and
blocks props get `no_producer` — the capture requests only SOG/points/goals/assists.

### NFL and NCAAF — `prop_evidence/football.py`

NFL: `nfl_prop_projections_<season>_wk<week>.json` (P(over), mean; **only wk1
exists in production**, so every later week is flagged STALE WEEK on the table),
`fantasy/nfl_fantasy_projections_<season>.json` (per-game means, target/carry/pass
share, depth rank, availability, week opponent), `smartsim2_projections_*` +
`smartsim2_segment_distributions_*` (score histograms), `schedule_<season>.csv`
(implied team totals, verified sign), `tracking/nflverse/injuries/*`.
Recent form is `artifact_missing`: `fantasy/nfl_fantasy_usage_*.json` is
allowlisted but production has none.
NCAAF: `player_game_stats/ncaaf_player_game_stats_snapshot.csv` for form and
opponent-allowed, `smartsim2_*` for the game. player_sim is `no_producer` — no
player projection is published and web must not model.

### Soccer — `prop_evidence/soccer.py`

`<league>/api/recommendations/<date>.json` `player_props[]` — the projections
Ask used to load and discard. **Shots, shots-on-target and (since `#673`,
2026-09-18) assists ladders are conditional on playing**; the anytime scorer
field is unconditional by user decision. Each probability field is stamped in
`ladder_conditioning` by `player_props.project_player_props`, and a file built
before the stamp is read by the exact test in
`soccer_projections.ladder_conditioning` (a ladder equal to Poisson on the
unconditional mean at 0.5 IS that; anything else is the start/sub mixture). Ask
and the board share that one function, so they cannot disagree; a row whose
ladder answers the other question from its market's is labelled, and the board
does not price it. The minutes share sits beside every row.
Form from `<league>/api/live_state/live_state_<date>.json` boxes (only since
2026-09-09, so samples are 1–2 matches). Season rates from
`<league>/players/<season>.csv`, with ESPN-league `xg_per90`/`xa_per90`
relabelled as goals/assists per 90.

### NCAAB — deliberately absent

`prop_evidence.NO_PROVIDER["ncaab"]`: no player model and no prop capture
(`scripts/fetch_basketball_oddsapi_props_local.py` covers NBA/WNBA only).

## The gate

    python scripts/prop_evidence_checklist.py
    python scripts/prop_evidence_checklist.py --base-url https://syndicate-an21.onrender.com \
        --sports mlb,wnba,nfl,ncaaf --sample 8 --json reports/prop_evidence/<date>.json

1. every `"title"` literal in the Ask data module maps to a layer;
2. every provider, on its production-sliced fixture, declares all seven layers
   and fills the ones `EXPECTED` names;
3. with `--base-url`, per-layer fill rates over real pregame board prop rows;
   an expected layer at 0 of ≥ `--min-rows` rows fails the run.

`EXPECTED` is the honest list, not the wish list — NFL recent form and NCAAF
player_sim are absent from it for the reasons above.

## Known gaps (measured, not fixed here)

* NFL per-game player stats never reach web; one worker run of
  `scripts/build_nfl_fantasy_usage.py --seasons 2025,2026` would fill NFL recent
  form (verified locally with the producer's own output).
* NFL prop artifact stops at week 1 and every row is `prior_season_fallback`.
* NHL `raw/player_game_stats.csv` has no scheduled producer.
* WNBA `boxscores_history.csv` bootstrap stalls (`#469`), newest game 2026-06-30.
* Soccer (`#673`, lane `soccer-prop-conditioning`): assists now price conditional
  on playing, like shots/SOT (H33, held out); each projection's as-of is its own
  match's file. The "4 of 12 fixtures never join" finding was RETRACTED: it was
  read in a worktree without `data/`, where the team-branding CSVs the soccer
  alias map is built from are absent; all four join on production.
* WNBA/NBA/NCAAF/NHL have no graded prop cells in the model scorecard yet
  (lane `model-scorecard-cron` owns that).
