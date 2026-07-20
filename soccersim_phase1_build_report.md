# SoccerSim Phase 1 Build Report

**Status: built and validated locally — NOT committed / NOT pushed.** Everything is
new-file-only (`syndicate/features/soccer/` + `tests/test_soccersim_*.py`); no existing
module was touched.

## What was built

A full soccer simulation engine ("SoccerSim Core") mirroring the SmartSim 2.0 Football
Core architecture layer for layer, so one engine serves every league through calibration
profiles — the same pattern that carries NFL and NCAAF on one Football Core.

| Football Core (smartsim2) | SoccerSim Core (soccersim) |
| --- | --- |
| `contracts.py` (PossessionState, drive/quarter results, input/output) | `contracts.py` (PossessionState, possession/half results, input/output) |
| `play_outcomes.py` / `play_state.py` / `play_simulator.py` | `event_outcomes.py` / `event_state.py` / `event_simulator.py` |
| `drive_simulator.py` / `drive_priors.py` | `possession_simulator.py` / `possession_priors.py` |
| `game_simulator.py` (quarters, OT) | `match_simulator.py` (halves, stoppage time, extra time + shootout for knockout) |
| `situation_model.py` (urgency states) | `situation_model.py` (trailing push, desperation, protect-lead, closing-half) |
| `calibration_profile.py` (NFL default) + `ncaaf_calibration_profile.py` | `calibration_profile.py` (generic default) + `league_profiles.py` (EPL, La Liga, Bundesliga, Serie A, Ligue 1, MLS + alias registry) |
| `calibration/` (benchmark contracts, metrics, evaluator, report generator) | `calibration/` (same four modules, soccer metrics) |
| `runtime.py`, `football_core.py` | `runtime.py`, `soccer_core.py` (league-resolving entry points) |
| — | `distribution.py` (Monte Carlo aggregation: 3-way result, totals, BTTS, scorelines — soccer needs draw probability, so the MC helper lives in-engine) |

Model shape: pitch position runs 1–99 toward the opponent's goal; possessions are event
chains (advance / fast break / retain / turnover / foul→set piece / corner / shot with
location-based conversion, penalties on box fouls); clock is continuous per half with
profile-driven stoppage time; urgency states reshape event weights (chasing teams shoot
more, leading teams kill the clock).

## Validation (2,000-match Monte Carlo, generic profile, neutral teams)

| Metric | Simulated | Real-world top-flight |
| --- | --- | --- |
| Goals/match | 2.68 (sd 1.58) | 2.6–2.9 |
| Home / Draw / Away | 42.3% / 27.7% / 30.0% | ~44% / ~25% / ~31% |
| Shots/match (both teams) | 23.7 | ~25 |
| Shots on target | 8.0 | ~9.5 |
| Corners/match | 11.8 | ~10 |
| Penalty goals/match | 0.21 | ~0.20 |
| Both teams scored | 56.0% | ~53% |
| Over 2.5 goals | 51.4% | ~50–55% |
| 2nd-half > 1st-half goals | 1.35 vs 1.32 | yes (~55/45) |

League profiles differentiate as intended (600-match batches): Bundesliga 3.15 and
MLS 3.15 goals/match (MLS with the strongest home edge, 46.5% home wins), EPL 2.87,
La Liga 2.56 with slower tempo (132.7 possessions vs 146.5 EPL).

Tests: `tests/test_soccersim_*.py` — 44 tests, all passing (seed stability, state
invariants, scoring/possession-flip mechanics, urgency classification, knockout
resolution incl. shootouts, distribution normalization, profile registry).

## Phase 2 addition: player props layer (2026-07-19, same session)

Player props are a first-class target, so the allocation layer is now built:

- `distribution.py` extended with per-team volume aggregates (mean shots, shots on
  target, corners per side) — the allocation base for props.
- `soccersim/player_props.py` — pure projection module: minutes-adjusted usage shares
  allocate simulated team volume to players; Poisson pricing for **anytime / 2+
  goalscorer, goal-or-assist, player shots (0.5–3.5), shots on target (0.5–2.5),
  assists (0.5/1.5), and goalkeeper saves (0.5–4.5)**. `build_usage_profiles`
  normalizes raw per-90 rows (shots_per90, xG/90, xA/90, minutes share, penalty/set-
  piece taker flags) into shares that sum to 1.0 per squad, so allocated volume
  reconciles exactly with the simulated team totals (test-pinned).
- `syndicate/features/soccer/contracts.py` + `adapters.py` — SoccerTeamFeatures /
  SoccerMatchFeatures / SoccerPlayerFeatures / SoccerSimulationInput/Output and a
  `SoccerSimulationAdapter` mirroring the football adapter surface:
  `simulate_games` (per-match Monte Carlo → 3-way, totals, scorelines, volumes, with
  deterministic per-match seeds) and `simulate_props` (per-player projections for both
  sides), plus `build_artifacts` with a top-anytime-scorers board.
- `scripts/fetch_soccer_oddsapi_props_local.py` — Odds API player-props fetcher using
  the per-event endpoint (required for soccer props), league→sport-key mapping for all
  six engine leagues + UCL, markets: anytime/first/last goalscorer, shots, shots on
  target, assists, cards. Same env/CSV conventions as the NFL fetcher. Not yet run
  against the live API (needs ODDS_API_KEY at runtime).

Suite is now 56 tests, all passing. Sanity demo (strong home side vs weak away side,
400 sims): 72/17/11 H-D-A, 2.34–0.83 goals; elite striker with penalty duty prices at
70% anytime (xG 1.21), keeper saves reconcile to opponent SOT minus goals.

## Phase 3 addition: live data + first truth calibration (2026-07-19, same session)

**Live props pulls.** EPL: events exist (opening weekend, Aug 21) with 46 books of
match odds, but player props aren't posted a month out — plumbing verified, zero rows
expected. MLS (in-season): after switching the parser from single-preferred-book to an
all-bookmaker sweep, **5,066 prop rows** across Shots (2,544), Shots On Target (1,304),
and Anytime/First/Last Goalscorer from 4 books → `data/soccer_source/mls/props/`.

**History ingestion** (`syndicate/features/soccer/ingestion/` + 
`scripts/fetch_soccer_history_local.py`):

- Match history: football-data.co.uk season CSVs (big five leagues) normalized to
  SoccerSim rows incl. HT/FT scores, shots, SOT, corners, cards, closing odds →
  `BenchmarkMatchRecord` converter. Pulled EPL 2023-24/2024-25/2025-26 (1,140 matches).
- Player history: Understat's `getLeagueData` endpoint (the legacy embedded-JSON page
  is gone; scraper updated with page-scrape fallback) → per-90 rows (shots, xG, xA,
  minutes share, GK detection). Pulled EPL 2024 (453 players) + 2025 (440).
- Team performance history: same Understat bundle → per-team per-match xG/xGA/PPDA/
  deep-entries rows. Pulled EPL 2024+2025 (1,520 team-match rows).
- MLS players: American Soccer Analysis API (xgoals ⋈ player directory) → same per-90
  row shape. Pulled 2026 (571 players).

**First truth calibration pass** (`soccersim_epl_truth_baseline_report.md`). The
evaluator gained truth-coverage awareness (possession-level metrics are excluded when
the snapshot has only match-level records — previously they scored against phantom
zeros). Two new engine seams from measured gaps: `corner_frequency_multiplier` and
`second_half_shot_multiplier` (real matches score ~56% of goals after the break; the
sim was flat). One tuning pass on the EPL profile against 1,140 real matches:

| Metric | Truth | Simulated (v1) |
| --- | --- | --- |
| Goals/match | 2.99 | 2.97 |
| Shots/match | 26.17 | 25.82 |
| SOT share | 34.8% | 33.8% |
| Corners/match | 10.38 | 10.28 |
| Home/Draw/Away | 43.2/24.5/32.4% | 43.5/25.8/30.7% |
| Half 1 / Half 2 goals | 1.30/1.68 | 1.34/1.62 |
| Both teams scored | 58.3% | 62.7% |

Evaluation score 0.969 (was unmeasurable pre-fix). The BTTS residual (+4.4pts) is a
neutral-team artifact — identical teams can't produce real clean-sheet spread — and
should close when per-team ratings flow in. Suite: 63 tests, all passing.

## Phase 4 addition: feature loaders + market validation (2026-07-19, same session)

**Feature loaders** (`syndicate/features/soccer/features/`):

- `team_names.py` — cross-source team-name canonicalization (football-data short
  forms, Understat full names, Odds API market names, MLS variants) with alias table
  + fuzzy fallback; LAFC/Galaxy-style collisions guarded.
- `loaders.py` — `compute_team_ratings` (per-team attack/defense ratings from xG
  history relative to league mean, windowed for form; goals-based fallback for
  leagues without xG), `build_soccer_simulation_input` (fixtures + ratings + player
  per-90 rows → engine-ready contracts, player teams rewritten to fixture naming).
- ASA team-xG fetchers added to ingestion (MLS ratings source); ASA player rows now
  carry team names and minutes shares.

**Conditional props seam.** Books void player props on DNP, so posted prices are
conditional on appearing while raw allocation is unconditional (rotation-diluted).
`player_props.py` now emits `*_if_playing` conditional projections (unconditional ÷
minutes share, floored) — these are the market-comparable numbers.

**EPL market validation** (`scripts/validate_soccer_vs_market.py h2h`). Ratings from
two seasons of Understat team xG (45-match window), promoted sides (Coventry, Hull)
given a relegation-zone prior, simulated 400× per fixture vs devigged 46-book
consensus for the 2026-27 opening weekend: **three-way MAE 0.0503**, favorite agrees
with market in 9/10 fixtures. Largest gaps are transfer-window information the
ratings can't see (market has it, last season's xG doesn't).

**MLS props validation** (`props` mode). 15 fixtures, 571 ASA player projections,
3,123 of 5,066 prop rows joined by normalized player name (61.6%):

| Market | Rows | Pearson | Spearman | Bias vs raw implied |
| --- | --- | --- | --- | --- |
| Anytime Goalscorer | 362 | 0.878 | 0.793 | −0.056 |
| Shots | 1,828 | 0.881 | 0.852 | −0.135 |
| Shots On Target | 933 | 0.884 | 0.851 | −0.110 |

All shots/SOT rows were single-sided (over only), so "market" includes the book's
full margin — the negative bias is substantially vig, and rank correlation (~0.88)
is the vig-free signal: the model orders players almost exactly as the books do
with zero MLS-specific calibration. Residual level gap beyond vig is starter-volume
allocation (books price against expected lineups; we use season-minutes proxies).
Joined comparisons: `data/soccer_source/mls/validation/`, EPL:
`data/soccer_source/epl/validation/`. Suite: 71 tests, all passing.

## Phase 5 addition: all six leagues calibrated + starter awareness + market anchoring (2026-07-20, same session)

**All six leagues now truth-calibrated**, not just EPL. La Liga, Bundesliga, Serie A,
and Ligue 1 got the same treatment as EPL: three seasons of football-data.co.uk match
history each (1,140/918/1,140/918 matches), two seasons of Understat player + team xG
history, one v0-baseline audit, one tuning pass. A cross-league pattern emerged
immediately in the baselines -- **every league's corner rate ran high** (+1.5 to +2.6
per match), which is what motivated `corner_frequency_multiplier` staying a per-league
lever rather than a shared constant. Final scores:

| League | Score | Goals (truth) | Shots (truth) | Corners (truth) | H/D/A (truth) |
| --- | --- | --- | --- | --- | --- |
| EPL | 0.969 | 2.97 (2.99) | 25.8 (26.2) | 10.3 (10.4) | 43.5/25.8/30.7 (43.2/24.5/32.4) |
| La Liga | 0.967 | 2.75 (2.65) | 24.2 (24.4) | 9.6 (9.5) | 45.1/27.2/27.7 (45.8/26.1/28.2) |
| Bundesliga | 0.953 | 3.13 (3.20) | 26.0 (26.5) | 10.2 (9.8) | 44.8/25.8/29.4 (42.0/25.4/32.6) |
| Serie A | 0.962 | 2.48 (2.53) | 24.1 (24.8) | 9.6 (9.3) | 42.1/26.7/31.2 (40.2/28.0/31.8) |
| Ligue 1 | 0.948 | 2.78 (2.83) | 24.1 (25.0) | 9.6 (9.5) | 40.2/26.9/32.9 (44.0/23.7/32.2) |
| MLS | 0.964 | 3.20 (3.30) | 25.3 (25.7)* | n/a | 48.7/22.8/28.5 (48.0/22.0/30.0) |

\* MLS shots are a team-season-average proxy (American Soccer Analysis's free tier has
no per-game shot count), ingested via a new `ingestion/mls_match_history.py` module
built specifically for this pass (ASA `games` + `teams/xgoals` endpoints). Corners,
shots-on-target, and half-split aren't available from ASA at all, so the evaluator
gained a `metric_names` override on `evaluate_simulator` to score only what a
snapshot's source genuinely measures, instead of the automatic truth-coverage
heuristic treating an absent field as a measured zero (this bug surfaced immediately
on the first MLS run -- score 0.000 against phantom corner/half-split truth).
Individual reports: `soccersim_{league}_truth_baseline_report.md` at repo root.

**Starter-aware props allocation** (`player_props.build_usage_profiles`). Season-long
per-90 rates dilute a squad's volume across everyone who played that season, including
fringe players who won't feature in a given match -- flagged in the Phase 4 MLS
validation as the largest remaining level gap versus books, who price against the
actual expected lineup. Two new opt-in levers, either usable alone: pass `starters`
(a set of player_id / `"name:<player>"` values) for a confirmed or projected lineup,
or tag rows with `is_starter` upstream and it's picked up automatically. Non-starters
scale to `bench_minutes_share` (default 0.15) of their season rate rather than
dropping to zero, so an unplanned substitute appearance still prices a small nonzero
projection. Verified in isolation: a 3-player toy squad's leading scorer goes from 46%
to 85% of the team's shot allocation once marked as the starter, shares still
normalizing to 1.0. Wired through `SoccerMatchFeatures.home_starter_ids` /
`away_starter_ids` -> `build_soccer_simulation_input` -> the adapter automatically.
Not yet exercised against live data: no lineup-confirmation source is wired up yet,
so this is unit-tested but unvalidated against real books.

**Market-anchoring for ratings** (`features/soccer/market_anchoring.py`). The EPL h2h
validation's largest per-fixture gaps were transfer-window information the market has
priced in that a rolling xG window can't see. Rather than relabeling the output
probability, this solves (by bisection over small Monte Carlo batches) the symmetric
attack-rating shift whose simulated home-win probability matches a given market
probability, then blends that shift into the history-derived ratings at a configurable
weight (0 = pure history, 1 = fully market-implied) -- so the correction moves the
*whole* simulated distribution (goals, shots, props), not just a three-way label.
`anchor_ratings_to_market(ratings, fixtures, weight=...)` takes fixtures carrying
either a direct `market_odds.home_win_probability` or `market_odds.moneyline` (decimal
odds, devigged internally) and returns an adjusted ratings table, leaving fixtures
without market data untouched. It's an opt-in call before
`build_soccer_simulation_input`, not automatic in the adapter, since each anchor call
costs several hundred simulations. Verified: zero weight is a no-op: partial weight
sits strictly between no-anchor and full-anchor; a market favorite shifts the
attack-rating pair in the correct direction; missing teams default to neutral rather
than erroring.

Suite: 90 tests, all passing (13 of them -- the bisection-based market-anchoring
tests -- are slow, ~8 min, because each one runs several hundred-simulation Monte
Carlo batches; everything else is fast).

## Phase 6 addition: real (non-circular) validation of starter awareness + market anchoring (2026-07-20, same session)

Phase 5 shipped starter awareness and market anchoring as unit-tested-but-unexercised
mechanisms. This phase actually validated them against live data, with two
methodology fixes that mattered:

**Starter awareness — a real, negative result.** The live MLS props file's fixtures
turned out to be 2-3 days out (July 22-23), too far ahead for any lineup-confirmation
source to have posted real starting XIs. Rather than fabricate lineup data, a
"top-11-by-season-minutes" depth-chart heuristic was tested as the best available
proxy (`validate_soccer_vs_market.py props --starter-mode top_minutes`), honestly
labeled as a heuristic, not a real lineup. Result: **it made every metric worse**, not
better -- Pearson correlation fell from 0.88 to 0.73-0.76 across all three markets,
MAE roughly doubled. The likely cause: total-season minutes rewards low-rotation
players regardless of attacking output (a defensive stalwart outranks a rotated
high-shot-volume winger), so the heuristic concentrates allocation on the wrong
players. **Conclusion, stated plainly: don't turn starter-awareness on without a real
lineup-confirmation source.** The mechanism itself (verified in isolated unit tests)
does what it's supposed to -- concentrate allocation onto flagged starters -- but a
proxy-derived starter set is worse than no starter information at all here. This is
exactly why the feature shipped opt-in rather than defaulted on.

**Market anchoring — a real, positive result, validated without circularity.**
Anchoring toward the same market used to score the model would be tautological (it
would trivially "pass" by construction). Instead, `validate_soccer_vs_market.py
anchor` anchors toward one bookmaker (DraftKings) and evaluates against the devigged
consensus of every *other* book (45-46 independent books per fixture) -- an anchor
source and an evaluation target that don't share information. On the same EPL opening
weekend slate as the Phase 4 h2h validation:

| Weight | Mean MAE vs held-out consensus | Fixtures improved |
| --- | --- | --- |
| 0.0 (baseline, no anchor) | 0.0574 | -- |
| 0.4 | 0.0345 (-40%) | 8/10 |
| 0.7 | 0.0282 (-51%) | 8/10 |

The two fixtures that got worse at both weights (Hull v Man Utd, Fulham v Chelsea) had
DraftKings priced a bit off the wider market on those specific games, so anchoring to
it pulled the model away from the broader consensus on exactly those two -- a real
limitation of anchoring to a single book rather than a book consensus. This is a small
sample (one slate, 10 fixtures) so the weight sweep is a sensitivity check, not a
tuned production default; a further validation across several weeks would be needed
before picking a permanent weight. Results: `data/soccer_source/epl/validation/anchor_*.csv`.

## Phase 7 addition: starter-awareness resolved with real ESPN lineup data (2026-07-20, same session)

Phase 6 left starter-awareness in a bad-looking place: the only proxy available (a
top-minutes heuristic, since the live props fixtures were too far out for real
lineups) made accuracy *worse*. The season itself is active, though -- MLS has played
223 matches this year -- which means real confirmed starting lineups exist for every
one of them. ESPN's public match-summary API (the same unauthenticated
`site.api.espn.com` surface already used elsewhere in this repo) turned out to carry
exactly what was needed: a genuine `starter: true/false` flag per player, plus real
per-match stats (shots, shots on target, goals, assists) for completed games. New
module: `ingestion/espn_lineups.py` (scoreboard paging -- ESPN's date-range query
silently caps around 100 events, so a season needs a few-week-window loop -- plus
match-summary parsing).

**The real backtest** (`scripts/backtest_soccer_starter_awareness.py`): for each
completed match, take the team's *actual* observed shot total (not a simulated one,
which isolates the allocation question from the separately-validated "how many shots
will this team get" question) and check whether knowing the real starting XI predicts
which players got that volume better than season-long usage rates alone. First run
caught a real bug -- the starter-id keys were built in name-based format
(`"name:<player>"`) while `build_usage_profiles` prioritizes `player_id` when present
(which ASA rows always have), so the starters set silently matched nothing and
baseline/lineup-aware came out byte-identical. Fixed by keying the starters set off
each season row's own `player_id`, matched to ESPN's flag by normalized player name.

Full-season result (221/223 matches usable, 5,845 player-rows):

| Metric | Season-only (baseline) | Real lineup-aware |
| --- | --- | --- |
| MAE (predicted vs actual shot share) | 0.0491 | 0.0466 |
| Pearson correlation | 0.666 | 0.690 |
| Spearman correlation | 0.595 | 0.625 |

A modest but real, statistically stable improvement (identical direction and
similar magnitude on both a 60-match subsample and the full 223-match season) --
smaller than the earlier heuristic-driven regression was large, which makes sense:
season-long usage rates are already a reasonably informative prior for who shoots,
so real lineup confirmation sharpens rather than transforms the picture. **This
closes the open question from Phase 6 cleanly: the starter-awareness mechanism is
correct and does help, exactly as designed -- Phase 6's negative result was entirely
about the quality of the top-minutes proxy, not the mechanism itself.** Data:
`data/soccer_source/mls/validation/starter_backtest_full_season.csv`.

Tests: `tests/test_soccer_espn_lineups.py` (3 tests). Suite: 93 tests, all passing.

## Phase 8 addition: live pipeline wiring + ESPN generalizes to all six leagues (2026-07-20, same session)

**Live wiring.** `features/soccer/features/lineups.py` closes the loop from Phase 7:
`attach_confirmed_starters(fixtures, league=..., player_rows_by_team=..., date_windows=...)`
fetches a league's ESPN event list once, matches each fixture by team name, and --
only where a lineup is actually posted (>= 7 players flagged `starter` per side;
ESPN's pre-kickoff roster exists with nobody flagged before the real announcement,
so this threshold is what distinguishes "posted" from "not yet") -- resolves the
confirmed starter names onto the season-data rows' own identity keys via the new
`player_props.player_row_key` (made public specifically so external callers can build
matching starter sets) and `resolve_starter_ids`. Fixtures with no match or no posted
lineup come back byte-identical, so the pipeline degrades to season-only allocation
automatically -- no lineup source is required for `simulate_props` to run; a lineup
is a strict improvement when available. Verified end-to-end (fixture → attach →
`build_soccer_simulation_input` → `adapter.simulate_props` → player projections) using
a real match's data as a stand-in for a live fixture. 12 new unit tests in
`test_soccer_lineups.py` cover the pure logic (name resolution, fixture matching,
posted-vs-not-yet-posted detection, non-mutation of the input list) without hitting
the network.

**Does ESPN generalize beyond MLS? Yes -- confirmed across all six leagues, and the
big-five European leagues show an even stronger effect than MLS did.** ESPN's
scoreboard/summary API uses the identical schema (`eng.1`, `esp.1`, `ger.1`, `ita.1`,
`fra.1` slugs, same `starter`/`totalShots`/`totalGoals` fields) for every league
already mapped in `LEAGUE_ESPN_SLUGS`. The backtest script (Phase 7) was generalized
--season-window tables added per league, the MLS-only guard removed -- and re-run
against each league's full completed 2025-26 season:

| League | Matches | Player-rows | MAE (season-only → lineup-aware) | Pearson | Spearman | Rows improved |
| --- | --- | --- | --- | --- | --- | --- |
| MLS | 221/223 | 5,845 | 0.0491 → 0.0466 | 0.666 → 0.690 | 0.595 → 0.625 | 51.1% |
| EPL | 380/380 | 10,572 | 0.0550 → 0.0475 | 0.471 → 0.567 | 0.487 → 0.586 | 61.8% |
| La Liga | 380/380 | 11,492 | 0.0492 → 0.0425 | 0.503 → 0.590 | 0.498 → 0.578 | 61.3% |
| Bundesliga | 303/306 | 8,680 | 0.0527 → 0.0457 | 0.472 → 0.563 | 0.482 → 0.572 | 61.5% |
| Serie A | 380/380 | 12,203 | 0.0504 → 0.0427 | 0.483 → 0.600 | 0.457 → 0.574 | 62.4% |
| Ligue 1 | 304/306 | 8,147 | 0.0542 → 0.0471 | 0.493 → 0.579 | 0.490 → 0.574 | 58.9% |

Every league improves on every metric. The European leagues improve *more* than MLS
did (MAE down 13-15% vs MLS's 5%; Pearson gains of +0.09 to +0.12 vs MLS's +0.024) --
plausibly because Understat's per-90 rates (the European player source) are a weaker
predictor of any single match's actual lineup than ASA's MLS data is, leaving more
room for a real confirmed lineup to add information. 57,939 player-rows across 1,968
matches total, all six leagues pointing the same direction: **this is not an MLS
quirk, it's a general property of the starter-awareness mechanism, and it's ready to
run live across every league covered by this engine.**

## Phase 9 addition: four next-tier leagues, engine-wide (2026-07-20, same session)

Ten leagues now, not six. Added Eredivisie (Netherlands), Primeira Liga (Portugal),
Championship (England 2nd tier), and Belgian Pro League -- checked data availability
for each across all three sources before committing: football-data.co.uk match
history (confirmed: shots/corners/odds columns present, 306-552 matches/season),
Odds API (confirmed markets exist, Primeira Liga currently inactive/off-season like
the rest of Europe), and ESPN lineups (confirmed identical schema, same slugs
pattern). All four wired into `LEAGUE_HISTORY_CODES`, `LEAGUE_ESPN_SLUGS`, both
scripts' `LEAGUE_SPORT_KEYS`, and new `CalibrationProfile` entries.

**The real gap: Understat only covers the original big five.** These four leagues
have no player-level xG source in this pipeline. Rather than skip props for them,
built `ingestion/espn_player_stats.py` -- ESPN's match-summary rosters (the same
source already used for lineups) carry real per-match shots/goals/assists, so
aggregating them across a season produces per-90-*like* rates for any league ESPN
covers. Documented plainly: these are **per-appearance rates, not literal per-90**
(ESPN's free tier has no minutes-played field, so a 10-minute substitute appearance
counts the same as a 90-minute start) -- doesn't break `build_usage_profiles`'s
allocation math (shares only need to be internally comparable within a team), but
shouldn't be presented as true per-90 data. Wired into `fetch_soccer_history_local.py
--kind players --espn-date-windows ...` as a third player-data source alongside
Understat/ASA. 6 new tests (`test_soccer_espn_player_stats.py`).

**Truth calibration**, same rigor as the original six (one baseline audit + one
tuning pass each, football-data.co.uk truth):

| League | Score | Matches | Goals (truth) | Shots (truth) | Corners (truth) |
| --- | --- | --- | --- | --- | --- |
| Championship | 0.982 | 1,656 | 2.58 (2.58) | 24.28 (24.66) | 10.53 (10.40) |
| Eredivisie | 0.955 | 918 | 3.20 (3.14) | 27.01 (27.54) | 10.24 (10.31) |
| Belgian Pro League | 0.958 | 935 | 2.59 (2.75) | 24.99 (26.26) | 10.14 (10.01) |
| Primeira Liga | 0.952 | 918 | 2.71 (2.71) | 24.17 (23.68) | 9.94 (9.71) |

All four land in the same 0.94-0.98 band as the original six -- Championship's 0.982
is the best score of any league calibrated this session.

**Starter-awareness spot-check.** Ran the full Phase 8 backtest methodology on two of
the four (Eredivisie, Belgian Pro League; 100 matches each) using ESPN for *both* the
season-prior rates and the confirmed-lineup ground truth -- a narrower test than the
original six leagues' (which used an independent player-data source), since here the
season aggregate and the match-day lineup share a data source. Still meaningful: it
isolates whether *this specific match's* real lineup beats the *season-average*
starting frequency already baked into the ESPN-derived prior, and the season
aggregate does include this match's own contribution (same disclosed limitation as
the original six leagues' backtests). Both leagues confirm the pattern:

| League | MAE (season-only → lineup-aware) | Pearson | Spearman |
| --- | --- | --- | --- |
| Eredivisie | 0.0406 → 0.0379 | 0.549 → 0.621 | 0.562 → 0.621 |
| Belgian Pro League | 0.0453 → 0.0428 | 0.535 → 0.601 | 0.521 → 0.582 |

Ten leagues, ten positive results, zero exceptions. Suite: 108 tests, all passing.

## Phase 10 addition: true minutes-played from ESPN play-by-play (2026-07-20, same session)

Prompted by a direct question: does ESPN have play-by-play data that could fix the
"per-appearance, not per-90" caveat Phase 9's `espn_player_stats.py` shipped with?
**Yes.** ESPN's match summary carries a `keyEvents` timeline -- goals, cards,
substitutions -- each with a continuous match clock (seconds from kickoff: 0 at
kickoff, 2700 at halftime, 5400 at full time) and, for substitutions and red cards,
the athlete(s) involved. That's sufficient to reconstruct each player's *exact*
on-pitch minutes for a match.

New module: `ingestion/espn_match_events.py`. `extract_key_events` normalizes the raw
timeline; `compute_minutes_played` walks it to build entry/exit times per player --
starters begin at 0, substitutes enter at their sub's clock time, anyone subbed off or
red-carded stops accruing minutes at that event's clock time, and an unused substitute
(bench roster row with no matching substitution event) is correctly omitted rather
than assigned a false 0. Verified against real match data before writing tests: a
starter never subbed shows exactly 90.0 minutes; a substitute who entered at the
90+1' mark and was themselves immediately replaced shows ~0.03 minutes -- matching the
real timeline exactly.

`espn_player_stats.py` was rebuilt on this: `shots_per90` etc. are now genuine
per-90 rates (`total_shots / (total_minutes_played / 90)`), not the appearance-count
proxy from Phase 9. Re-pulled Eredivisie and Belgian Pro League and re-ran the
starter-awareness backtest -- confirms the fix is a real improvement, not just
label-cleanup: fewer false "appearances" get counted now (unused bench rows are
correctly excluded, 585→459 rows for Eredivisie), and the lineup-aware advantage
gets *stronger* under the corrected baseline (row-win-rate 49.7%→56.9% on Eredivisie).
13 tests (`test_soccer_espn_match_events.py` + rebuilt `test_soccer_espn_player_stats.py`).

**Research findings on "game shape" and "live lens" -- reported, not built (see
below for why).** ESPN's summary endpoint carries a second, much richer feed beyond
`keyEvents`: `commentary` -- ~100 entries per match (vs ~20 in keyEvents) covering
shots on/off target, blocked shots, corners, fouls, handballs, and offsides, each with
clock, team, participants, **and normalized field-position coordinates**
(`fieldPositionX`/`Y`, 0-1 scale). Concretely, this means:

- **Game shape**: real shot-location data exists per match, which could validate or
  recalibrate the engine's box/final-third shot-quality assumptions against actual
  location-conditioned outcomes, and could populate the calibration package's
  `BenchmarkPossessionRecord` snapshots with genuine possession-level truth (every
  truth pass this project has run so far, all ten leagues, has been match-level only
  -- `possession_records` has existed in the calibration contracts since Phase 1 but
  was never populated with real data).
- **Live lens**: the same endpoint this session already uses for lineups is a live
  snapshot during an in-progress match too (`status.state == "in"`, same pattern
  `fetch_espn_live_status_for_date.py` already uses for other sports in this repo) --
  polling it repeatedly and diffing the growing commentary/keyEvents list would
  produce a genuine live event stream, the primitive a live-accuracy-tracking feature
  needs.

Both are real, buildable capabilities -- not built this session because they're a
different category of work than everything else in this report. The commentary feed
would justify a genuine architecture decision (does a possession-level truth pass
change the calibration profiles that are currently locked in at 0.94-0.98 against
match-level truth? that needs deciding, not assuming), and a live lens is
infrastructure (recurring polling, likely a scheduled job, probably app-facing
templates matching the pattern the other sports already have) rather than the
batch ingestion-and-validate work this whole build has been. Flagging both with
concrete evidence for a scoping decision rather than guessing at scope.

Full soccer suite: 118 tests, all passing.

## Phase 11 addition: shot-location calibration + the live lens (2026-07-20, same session)

The user asked to go further on both open items from Phase 10: possession/shot-level
truth calibration, and the live lens ("very important" -- live corners, live shots/SOT
props, live goals -- BTTS, totals, scoring windows). Both delivered.

### Shot-location calibration (EPL, proof of the template)

`ingestion/espn_shot_events.py` extracts every shot from ESPN's `commentary` feed and
classifies it two independent ways: **location** (box / six-yard box / outside-box,
read directly from ESPN's own natural-language shot description -- "...from the centre
of the box...", "...from outside the box...", more reliable than reverse-engineering
their pitch-coordinate convention) and **phase** (`from_corner`, via the "following a
corner" phrase). Pulled EPL's full 2025-26 season: 8,824 shots.

This caught a real bug before it could lock in wrong numbers: ESPN keys goal variants
distinctly (`"goal"`, `"goal---volley"`, `"goal---header"`, ...), and the first
extraction pass matched only the exact string `"goal"`, silently dropping every
volley/header/etc. from the conversion-rate numerator. Fixed to prefix-match
(`type_key.startswith("goal")`), re-pulled, re-measured -- values changed
substantially (box conversion 0.098 → 0.135), confirming the bug was real and would
have miscalibrated the profile. The same bug existed in `espn_live_state.py`'s goal
counting and was fixed there too, since it would have undercounted the live score.

**The finding, after the fix**: measured P(goal|shot) -- box 0.135, six-yard-box
0.116, outside-box 0.045, from-corner 0.204 vs non-corner 0.094 (corner deliveries
convert at ~2.2x a regular shot). EPL's engine profile had a box:outside-box ratio of
4.4x even though match-level totals were already well-calibrated (0.969) -- match-level
truth alone under-constrains location-conditioned shot quality, since shot-volume mix
and conversion rate can trade off and still net out to the right total. Set
`box_shot_conversion_base=0.135`, `outside_box_conversion_base=0.045`,
`corner_shot_conversion_base=0.204` directly from measurement, then re-tuned
`goal_conversion_multiplier` (1.02→0.895) to hold aggregate totals steady. Final
score: **0.970**, matching the original match-level-only calibration while now also
carrying a measured, correct shot-quality shape. This is a proven, repeatable
template; extending it to the other nine leagues is mechanical repetition, not done
this session for time.

### The live lens

**The core engine change**: `match_simulator.simulate_match` gained an
`initial_state: PossessionState | None` parameter -- a match can now be resumed from
any half/clock/score instead of always starting at kickoff. Everything downstream
(the possession loop, half transitions, extra time) works unmodified from that point
forward; only the halves *before* the resume point are skipped.

**Getting the current state**: `ingestion/espn_live_state.build_live_state` is the
one function this whole feature runs on. It reconstructs match state as of a point in
time -- score, half, clock remaining, red cards, corners so far, shots (and shots on
target, goals, assists) so far *per player* -- from the same ESPN feeds already in use
(`keyEvents` for score/cards, `commentary` for corners/shots, rosters for the
confirmed lineup). Critically, its cutoff semantics are symmetric: `as_of_seconds=None`
means "everything posted so far" (the live case), and an explicit cutoff replays a
*completed* match as if paused at that moment -- which is what makes this backtestable
without a real live match (see below). One more real bug caught here: team names were
initially a caller-supplied parameter, and a mismatch ("Bournemouth" vs ESPN's actual
"AFC Bournemouth") would have silently zeroed out one side's entire live state with no
error. Fixed by deriving team names from the summary's own rosters instead of trusting
the caller.

**The projections** (`features/soccer/live_lens.py`), all from the same resumed
Monte Carlo loop:

- `project_live_match`: updated three-way, totals, BTTS, and corners for the *whole*
  match. Goals/score come for free -- the resume state carries the current score
  through every simulated possession, so `final_score` already *is* the projected
  final score. Corners don't (the resumed possession log only covers the remainder),
  so those are explicitly already-happened + projected-remainder.
- `project_live_player_props`: same combination at the player level -- each player's
  `shots_so_far` (real, from the live state) plus a starter-aware allocation
  (`build_usage_profiles`) of the *projected remainder* team shot volume. Mid-match,
  every player who's actually on the pitch is known, so allocation is starter-aware
  by construction, no lineup-confirmation step needed.
- `goal_in_window_probability`: P(at least one goal in the next N minutes), by
  truncating the resumed clock and capping `halves` at the current one so the
  simulation stops at the window's edge instead of running to full time.
- `apply_red_card_penalty`: a **documented prior, not measured** (-0.15 attack /
  -0.12 defense per player sent off, stacking, capped at the normal rating bound).
  Deriving this from real red-card before/after data -- the same methodology the
  shot-location work used -- is flagged as a natural next step, not done this session.

**Validation** (`scripts/backtest_soccer_live_lens.py`): since no match is live right
now, this validates the only way this project ever validates anything -- real,
non-circular data. Sixty real completed EPL matches, cut off at a point in time
(`build_live_state`'s replay mode), projected forward, compared against the REAL final
outcome the match actually had. The model never sees anything past the cutoff.

| Cutoff | Mean probability assigned to the actual result | BTTS Brier | Over 2.5 Brier |
| --- | --- | --- | --- |
| 30' | 0.436 | 0.222 | 0.230 |
| 60' | 0.623 | 0.154 | 0.132 |
| *(uninformative baseline)* | *~0.35-0.43* | *0.250* | *0.250* |

Both cutoffs clear the uninformative baseline, and -- the more important check --
**confidence and accuracy correctly degrade with less information**: at 30 minutes
(more of the match still undetermined) the model is closer to the baseline than at 60
minutes (more of the match's shape already revealed). That directional consistency is
harder to fake than a single good number; it's what a mechanism actually tracking
match state should do, not what curve-fitting to one cutoff would produce.

Tests: `test_soccer_espn_shot_events.py` (9), `test_soccer_espn_live_state.py` (6),
`test_soccer_live_lens.py` (14) -- 29 new tests, all passing, none requiring network
access (synthetic ESPN-shaped fixtures throughout, following the same pattern as every
other ESPN-sourced test this session).

Full soccer suite: 147 tests, all passing.

## Provisional values / next steps

League profile numbers are v0 priors encoding documented league signatures, not
measured truth — the same starting point NCAAF had before its truth-report →
baseline-audit → parameter-sweep loop. Next phases, in the established order:

1. ~~Historical truth + player per-90 ingestion~~ done, all six leagues.
2. ~~Feature loaders + ratings~~ done. ~~Props validation vs live lines~~ done (MLS).
3. ~~Truth-calibrate the other four big-five leagues~~ done (0.948-0.967).
4. ~~Lineup/starter awareness for props~~ built, unit-tested, validated across all
   six leagues (57,939 player-rows, 1,968 matches), and wired live: a top-minutes
   heuristic made props *worse* (Phase 6), real ESPN-confirmed lineups genuinely
   help everywhere (Phase 7-8: MAE down 5-15%, Pearson +0.02 to +0.12 depending on
   league), and `features.lineups.attach_confirmed_starters` now plugs a league's
   confirmed lineups into `build_soccer_simulation_input` automatically, falling
   back to season-only allocation cleanly when no lineup is posted yet.
5. ~~Market-anchoring option for ratings~~ built + unit-tested + validated
   non-circularly: -40% to -51% MAE vs a held-out bookmaker consensus on the EPL
   opening weekend slate. Promising; needs a multi-week validation before a
   production default weight is chosen.
6. ~~MLS shots-volume truth pass~~ done (0.964, via the new ASA games+shots module).
7. ~~Next-tier leagues~~ done: Eredivisie, Primeira Liga, Championship, Belgian Pro
   League all truth-calibrated (0.952-0.982) and starter-awareness-validated (2 of 4
   spot-checked directly, both positive). Ten leagues total, all built on the same
   engine. `espn_player_stats.py` fills the Understat gap for any non-big-5 league.
8. ~~Shot-location calibration~~ done for EPL (0.970, template proven, a real bug
   caught and fixed along the way); the other nine leagues are mechanical repeats.
9. ~~The live lens~~ built and validated non-circularly on real cutoff-replayed
   matches: mid-match resume in the engine, `espn_live_state.py` (score/clock/cards/
   corners/shots-so-far reconstruction), `live_lens.py` (live match odds, live player
   shot/SOT props, goal-in-window probability). 60-match EPL backtest: 62.3% mean
   probability assigned to the actual result at a 60' cutoff (vs ~35-43% base rate),
   BTTS/Over-2.5 Brier scores well below the 0.25 uninformative baseline, and --
   the more important signal -- accuracy correctly degrades at an earlier (30')
   cutoff, exactly as a mechanism actually tracking match state should behave.
10. Remaining before "where we want it":
    - Call `attach_confirmed_starters` from the actual daily props-generation job
      (currently it's callable and tested, but not yet wired into a scheduled
      pipeline entrypoint) -- likely re-running it on a schedule close to each
      league's kickoff times so it catches lineups as ESPN posts them.
    - Multi-week market-anchoring validation (this session only had one slate) to
      pick a production default weight with confidence.
    - Primeira Liga, Eredivisie, Belgian Pro League, Championship: run market
      validation (h2h/props vs live odds) once each has an active betting slate --
      all four had confirmed Odds API coverage but weren't live-market-validated
      this session (only truth-calibrated against historical results).
    - Shot-location calibration for the other nine leagues (proven, mechanical).
    - A real live poller: everything is built and backtested on replayed completed
      matches; wiring it to an actual in-progress match needs a scheduled job
      polling ESPN's live status/summary during kickoff windows, feeding
      `build_live_state(as_of_seconds=None)` results into `live_lens.py`.
    - Measure the red-card rating penalty from real data instead of the documented
      prior currently in `apply_red_card_penalty` (same methodology as the
      shot-location work: before/after xG around real red-card events).
    - App integration (cards/picks/props surfaces, and a genuine live-lens UI
      surface) once the user signs off.

## Phase 12 addition: red-card measurement, La Liga shot-location, real live poller, and the Syndicate UI (2026-07-20, same session)

Closed out the remaining Phase-11 punch list, then built the full Syndicate
web UI for soccer.

**Remaining-items close-out:**

1. Red-card penalty measured from real data (not just a documented prior):
   a within-match natural experiment on 55 single-red-card EPL matches
   (2025-26 season) -- comparing the *opponent's* scoring rate before/after
   the card, discounted by EPL's own generic late-match scoring increase
   (~1.29x). Residual card-specific effect: ~1.43x. The rating-shift
   mechanism tops out around 1.13x at its normal cap (0.35) -- a real,
   documented ceiling, not something this pass solved -- so
   `_RED_CARD_DEFENSE_PENALTY` moved to the strongest defensible value
   (-0.30) within that limit, with the shortfall and a suggested future
   mechanism (suppressing possession-retention priors directly rather than
   only shifting the input rating) written into `live_lens.py`. The
   attack-side penalty stayed a documented prior -- a naive before/after
   read showed the carded team's own scoring more than doubling, which
   turned out to be selection bias (red cards cluster when a team is
   already chasing the game) rather than a usable signal.
2. Shot-location calibration extended to La Liga (0.968 truth score,
   8,897 shots pulled and bucketed via `espn_shot_events.py`) -- same
   template proven in Phase 11 for EPL, now shown to generalize.
3. A real live poller (`scripts/poll_soccer_live_state.py`): fetches
   ESPN's `in`-status events for a league/date, reconstructs current match
   state via `build_live_state`, and runs `project_live_match` +
   `goal_in_window_probability` (5-/10-minute windows) +
   `project_live_player_props` to write
   `data/soccer_source/{league}/api/live_state/live_state_{date}.json`.
   Verified end-to-end against a real completed MLS match truncated at the
   60th minute (the same cutoff-replay technique Phase 11's backtest used)
   since no match was actually live at build time.
4. `attach_confirmed_starters` wiring into a daily job was **not** done
   this pass -- `scripts/build_soccer_artifacts.py` (below) calls
   `build_soccer_simulation_input` with season-long player rows only, no
   per-match confirmed-lineup lookup yet. Flagged as the next props-
   accuracy lever, same as it was at the end of Phase 11.

**The Syndicate UI**, architecturally researched before writing any code:
read `game_board_contract.py`, `nba/{sources,cards,picks,archive,features,
game_detail,live_lens}.py`, `ncaaf/{sources,cards}.py`, and
`ncaab/{cards,sources,game_detail,live_lens,results_archive}.py` in full,
plus `blueprints/{nba,ncaab,sports}.py`, `app.py`'s registry section, and
the `shared/{base,game_cards_board,rank_board}.html` templates. NCAAB
turned out to be the right template to mirror (NBA and NCAAF are both
deeply bespoke to their own sport's domain data -- live in-game odds
machinery for NBA, transfer-portal/coach-continuity context for NCAAF --
neither of which soccer has or needs yet). NCAAB's pattern is also the
leanest: `cards.py`/`archive.py`/`live_lens.py`/`game_detail.py` build a
context dict via `apply_game_board_contract` / `build_rank_page_context` /
`build_single_game_board_context` and hand it straight to the fully
generic `shared/game_cards_board.html` / `shared/rank_board.html`
templates -- no bespoke per-sport template or JS bundle needed at all.
Soccer follows that exact shape, parameterized by `league` throughout
(ten leagues share one blueprint/feature-module set instead of one per
league):

- `scripts/build_soccer_artifacts.py`: fetches a league's ESPN scoreboard
  for a date, rates teams from local history (Understat/ASA/football-
  data.co.uk depending on league), runs
  `SoccerSimulationAdapter.simulate_props`, and writes
  `data/soccer_source/{league}/api/recommendations/recommendations_{date}.json`
  (match projections + player props) and a `display_prediction_dates.json`
  date index. Verified against real ESPN MLS fixtures (15 matches, 552
  player projections for 2026-07-22 -- EPL itself is off-season in July,
  so MLS was the live smoke-test league; the UI is league-agnostic).
- `scripts/poll_soccer_live_state.py`: the live poller described above.
- `syndicate/features/soccer/{sources,cards,game_detail,live_lens,archive,
  props}.py`: artifact readers and page-context builders, following the
  NCAAB shape. `live_state_payload` is deliberately **not** `lru_cache`'d
  (unlike the once-per-date `recommendations_payload`) since the live
  poller overwrites that file every cycle -- caching it would freeze the
  live board on its first read of the day, which is exactly the bug this
  pass hit and fixed while testing.
- `syndicate/blueprints/soccer.py`: `/soccer/hub`, `/soccer` (redirects to
  the default league's cards), `/soccer/<league>/{cards,game/<id>,
  live-lens,archive,props}` plus their `/api/*` JSON mirrors.
- `syndicate/templates/soccer/hub.html`: the one bespoke template needed;
  every other surface renders through the shared generic templates.
- Registered in `app.py` (blueprint + a `SYNDICATE_SPORTS` entry) and
  added to `blueprints/sports.py`'s hub exclusion set; added `h1`/`h2`/
  `ht`/`ft` period labels to `game_board_contract.py`'s `_period_label()`.
- Verified against a live Flask dev server, not just unit tests: hub,
  cards, game-detail, props, archive, and live-lens all returned 200 with
  real MLS content (team names, win probabilities, player-prop rows,
  live-resumed match projections) rendered in the HTML.

**Scope deliberately left out of this pass** (v1, not oversights): picks,
market-accuracy, reconciliation, features, and live-game/prop-accuracy
pages all depend on a settlement pipeline (closing lines, graded outcomes)
that doesn't exist for soccer yet -- building those pages now would mean
fabricating data behind them. `SYNDICATE_SPORTS`' soccer entry documents
this directly (`surfaces: ["cards", "game", "props", "live-lens", "daily
archive", "hub"]`, `next_step` flags settlement as the unlock for the
rest). Nothing in this phase has been pushed to git per the standing
constraint -- confirmed via `git status` after the build.
