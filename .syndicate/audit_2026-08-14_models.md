# Model audit — 2026-08-14

> Read-only pass. No code changed. Evidence tags: `[measured]` = read from
> production or from a file this session; `[from-code]` = read from source;
> `[unverified]` = neither, stated as open.
>
> Production reads in this note are against web `f9aa2399` (deployed
> 2026-08-14 12:45 CDT), taken 12:55–13:10 CDT. Local HEAD `0a18d901` has
> DIVERGED from the deployed tree — parallel sessions. Re-read before relying
> on any commit-scoped claim here.

---

## 0. The three findings that matter

1. **CLV has never been computed for a single bet or recommendation.** Not
   "sparse" — zero. 8,276 recommendation records, 0 settled; 3 tracked
   positions, 0 settled, `avg_clv: null`. `[measured]`
2. **The edge gate is inert, and its inertness is downstream of (1).** Every
   adaptive term in `filter_candidates`'s threshold requires
   `settled_count >= 3`. With 0 settled, the threshold collapses to a bare
   `edge > 0`, and the published board's floor is a *hold-calibrated junk
   filter*, not a skill threshold. `[measured]` + `[from-code]`
3. **69 sport × market pairs ship a prediction. Two have a backtest.** NFL
   preseason (n=146 games) and MLB hitter props (n=2,487 player-games) — and
   the MLB one is **not in the deployed tree**. `[measured]`

---

## 1. Inventory

### Where model definitions live

Scattered, per sport, with **no shared interface**. There is no `fit`/`predict`
protocol, no ABC, no common feature-builder. Five independent engine families:

| family | location | shape |
|---|---|---|
| smartsim2 (NFL, NCAAF) | `syndicate/features/football/sim_engine/smartsim2/` | play → drive → game Monte Carlo |
| soccersim | `syndicate/features/soccer/sim_engine/soccersim/` | possession → event Monte Carlo |
| hockeysim | `syndicate/features/nhl/sim_engine/hockeysim/` | Poisson/λ + market anchoring |
| basketball smart-sim (NBA, WNBA) | `syndicate/features/shared/basketball_props_smart_sim.py` | per-stat mean + fixed σ |
| MLB daily sim | `scripts/run_mlb_daily_sim_job.py` → `daily_summary_*.json` | full Monte Carlo, writes distributions |

Three of the five (football/soccer/hockey) share a *structural convention* —
each has its own `contracts.py`, `calibration_profile.py`, `runtime.py` — but
the dataclasses are unrelated types. `calibration_profile_store.py` was written
to generalise across all three; **nothing outside `tests/` imports it.**
`[from-code]`

**What actually runs** is enumerable, not inferred: `sim_run_ledger.py`'s
`_SIM_COMMAND_PATTERNS` is the classifier every non-MLB sim passes through.
Ten patterns, seven sports. NCAAB has no in-repo model at all — it reads
`predictions_model_calibrated_*.csv` produced elsewhere. `[from-code]`

### Sport × market pairs producing a prediction today

**A. Joined to the shared board** (`board_enrichment.attach_projections`, the
13-return-site choke point) — **43 pairs, 4 sports**:

| sport | markets | n |
|---|---|---|
| mlb | pitcher: strikeouts, outs, hits_allowed, earned_runs, walks_allowed, batters_faced, pitches · hitter: hits, total_bases, rbis, runs, hits_runs_rbis, doubles, triples, stolen_bases, home_runs | 16 |
| wnba | h2h, spreads · points, rebounds, assists, threes, steals, blocks, turnovers, PRA, PR, PA, RA | 13 |
| soccer | h2h, h2h_3_way, totals, totals_alt, spreads, spreads_alt, anytime_scorer, shots, shots_on_target, first_scorer, last_scorer | 11 |
| nfl | h2h, spreads, totals | 3 |

`_attach_projections_by_sport` explicitly returns `supported: False` for nba,
nhl, ncaaf, ncaab. `[from-code]`

**B. Predictions rendered in their own sport module, no board join** —
**26 pairs, 3 sports**:

| sport | markets | n |
|---|---|---|
| nba | 13 basketball prop markets (incl. double_double, triple_double) | 13 |
| nhl | moneyline, total, puck line, F10 · SOG, goals, assists, points, blocks, saves | 10 |
| ncaaf | spread, total, moneyline (from margin_mean/total_mean/home_win_rate) | 3 |

**C. External producer**: ncaab.

**Total: 69 pairs.** The brief's threshold for "breadth is the problem before
anything else" is ~10.

### Live vs. leftover

Everything above is invoked at runtime — verified via `sim_run_ledger`
patterns, blueprint imports, and the board's own coverage payload. Confirmed
**dead or inert**, by call-site grep rather than filename:

- `calibration_profile_store.py` — tests only. The refit seam exists; nothing
  refits. NFL's profile is all-1.0 multipliers.
- `shadow_candidate_ledger.py` — wired at `intelligence_state.py:4198`, gated
  on `SYNDICATE_SHADOW_CANDIDATE_LEDGER_ENABLED`, **key unset** → off. So
  filter precision (how good were the candidates we rejected?) is still
  unmeasurable.
- `model_scoring.binary_calibration_metrics` — reached only through
  `intelligence_evaluation`, which needs settled records. 0 settled → inert.

Two modules that look like models and are not: `live_projection_join` (a join —
its own docstring says so) and `game_board_contract` (`_first_present(...)`
passthrough). This confirms state.md's "`#428` is four models, not six" — do
not write harnesses for these.

---

## 2. Validation — the highest-priority section

### Is there a backtest at all?

**Yes, six scripts. They cover 2 of 69 pairs' worth of published skill
numbers.** No harness covers NBA, NHL, NCAAF, NCAAB, WNBA props, soccer
pregame markets, or MLB pitcher props.

| script | target | scores against | n | verdict emitted? |
|---|---|---|---|---|
| `backtest_nfl_preseason_projection.py` | NFL preseason win rate | **outcomes** (final score) | 146 games / 3 seasons | yes → `nfl_preseason_calibration.MEASURED_SKILL` |
| `backtest_mlb_props.py` | MLB hitter prop means | **outcomes** (box score) | 2,487 player-games / 14 dates | yes → `mlb_prop_calibration` |
| `backtest_wnba_projection.py` | WNBA `pred_margin`/`pred_total` | **outcomes** (ESPN finals) | blocked: 9 of 361 completed games carry the column | no |
| `backtest_nfl_injury_adjustment.py` | one adjustment, not the model | outcomes | — | no |
| `backtest_soccer_starter_awareness.py` | prop *allocation* only | observed shot volume | 60–100 matches | no |
| `backtest_soccer_live_lens.py` | live forward-projection only | outcomes at cutoff | 60 matches | no |
| `validate_soccer_vs_market.py` | model vs. **live** devigged consensus | market agreement | — | no |

**Nothing anywhere scores against the closing line.** Every harness that scores
at all scores outcomes — the high-variance instrument the brief warns about.
`prediction_ledger.py`'s own docstring already makes the argument against this
(outcome ROI on ~1,100 bets: CI95 `[-7.6%, +3.8%]`; the paired price comparison
on the same data: `[+2.48, +3.13]`) and nothing acts on it.

**Results are per-sport, not pooled** — that part is right, and deliberately so
(`--min-games` refusal thresholds, per-market denominators, `n` travelling with
every statistic). The honesty discipline in these harnesses is genuinely good;
the problem is coverage and what they measure, not rigour.

### Walk-forward?

**Two designs, and only one of them is sound.**

- **Archive-replay (MLB props, WNBA)** — reads the *published production
  artifact for that date* via `/api/ops/artifacts/stream` and joins to the real
  outcome. Point-in-time correct **by construction**: the artifact is a frozen
  record of what the model actually said that day. There is no fitting step to
  leak through. **This is the right pattern and should be the template.**
- **Regenerate-in-memory (NFL preseason)** — genuinely walk-forward at season
  granularity: `prior_plays = load_pbp_plays(season - 1)`, and
  `team_rating(..., before_week=week)` filters plays to before the target week.
  `[from-code]`

Neither is a random train/test split. Good.

**One in-sample caveat on the MLB harness:** the de-bias correction
(`bias = mean(pred - actual)`, then re-score) is estimated on the *same* sample
it is scored on. The constant baseline is also in-sample, so the comparison is
roughly one-free-parameter to one-free-parameter and not grossly unfair — but
"de-biased beats baseline by 0.035" is an in-sample number and will shrink
out-of-sample. Splitting the window (fit bias on dates 1–7, score on 8–14) is a
half-hour change and makes the published verdict defensible.

### Point-in-time correctness, per feature source

| feature source | used by | verdict |
|---|---|---|
| nflverse pbp EPA, `_mean_epa(..., before_week=week)` | NFL, NCAAF smartsim2 | **SAFE** — explicit week cutoff `[from-code]` |
| prior-season pbp fallback | NFL preseason | **SAFE** — `season - 1` only |
| MLB daily sim inputs | MLB props | **SAFE for the backtest** (archive replay). Model-side as-of-ness **UNKNOWN** — not traced this pass |
| soccer team xG ratings (`compute_team_ratings`) | soccer pregame, **and its backtests** | **UNSAFE in backtest** — see below |
| soccer usage profiles (`build_usage_profiles`) | starter-awareness backtest | **UNSAFE** — season-long profiles applied to matches inside that season |
| WNBA/NBA per-stat means | basketball props | **UNKNOWN** — no harness reaches them |
| hockeysim λ + market anchoring | NHL | **UNKNOWN**, and market-anchored: the market is an *input*, so CLV against it is near-circular by construction. Flag before any NHL CLV number is believed |
| ncaab calibrated predictions | ncaab | **UNKNOWN** — produced outside this repo |

**The confirmed leak, stated precisely.** `compute_team_ratings` takes
`team_history_rows` and keeps each team's *last N* rows. It has **no date
parameter** — point-in-time-ness is entirely the caller's responsibility.
`backtest_soccer_live_lens.py:47` computes ratings **once**, from
`sorted(history_dir.glob("teams_*.csv"))` concatenated — the full season — and
then backtests matches sampled across `20250801`–`20260531` with that single
rating set (`_LEAGUE_SEASON_WINDOWS`, lines 39–43). A September 2025 match is
predicted using xG from matches played through May 2026. This is exactly the
brief's first trap: a season-to-date aggregate recomputed from a current table.
`backtest_soccer_starter_awareness.py` has the same shape via
`build_usage_profiles`. `[from-code]`

**Production soccer is NOT affected** — `build_soccer_artifacts.py` uses the
same function to predict *forward* fixtures, where "everything to date" is
correct. The leak is confined to the validation scripts, which means every
number in `data/soccer_source/*/validation/*_backtest_*.csv` is optimistic by
an unmeasured amount and should not be cited.

**No closing-line-derived value is used as a feature anywhere** — checked.
`market_anchoring` (soccer, NHL) uses *current* prices as an input, which is
legitimate for a projection but makes market-relative evaluation of those two
engines circular. That is a scoring caveat, not a leak.

---

## 3. Closing-line value instrumentation

### Is the schema there? Mostly yes.

`prediction_ledger.PredictionRecord` carries timestamp, `model_probability`,
`implied_probability`, `odds`, and a `quote` block (book, number, when that book
last moved, rank against every other book at that instant) — the opening half.
`PredictionResult` carries `original_price`, `closing_price`, `clv_pct`,
`beat_close`, with the sign convention documented and `beat_close` left `None`
rather than `False` when uncomputable. `odds_refresh_tracking` stamps a real
`closing_line`/`closing_price` on `market_state` at the actual pregame→live
transition, and `evaluation_settlement` prefers that stamp over the graded row's
own price *only when* `history_points > 0` — a correct guard against
`build_market_history_view`'s no-history fallback, which relabels the opening
price as "closing" and would produce a fake zero CLV.

**The design is right. It has produced nothing.**

### What production actually holds `[measured 2026-08-14 ~13:00 CDT]`

`GET /api/ops/evaluation-settlement/status`:

```
total_recommendation_records  8276
pending                       8276
matched                          0
settled                          0
unmatched                     8276
  ├─ no_graded_rows            3716
  └─ no_key_match              4560
```

`GET /api/portfolio/summary`:

```
total_tracked   3      settled_count  0
avg_clv       null     avg_edge     null     roi  null
```

So: **CLV per sport, per market, per confidence bucket cannot be produced.**
There is no bucket with a denominator above zero.

### Why — three separate causes, and they need separate fixes

1. **The ledger window is 19/21 days empty.** `chunk_diagnostics` shows
   `exists: false` for 2026-07-17 → 2026-08-04. Only 08-05 and 08-06 exist.
2. **The two chunks that exist are enormous**: `2026-08-05.jsonl` is
   **367,229,260 bytes over 9,055 lines** — ~40 KB *per record*. This is the
   bloat `shadow_candidate_ledger`'s docstring was written to avoid, present in
   the real ledger. It is also why the settlement autorun is disabled: the
   render.yaml comment records `O(records × chunk_bytes)` with the whole chunk
   rewritten and the index round-tripped **per record**.
3. **The join fails even when both sides exist.** `graded_rows_available` is
   `{mlb 2026-08-05: 1}` and **zero for every other sport-date**. Of the
   4,560 `no_key_match` failures, the sampled reasons show prop and totals
   records being matched against a graded set whose only market family is
   `moneyline`. The grading side is not producing rows, so the settlement side
   has nothing to match against.

**`EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN` is off** — blueprint
default `false`, `sync: false`, and the code treats absent as False. But note:
turning it on today would settle **zero**, because `matched: 0` is a dry-run
result measured independently of the autorun. Flipping the flag is not the fix
and would only spend memory.

### Smallest change that starts capturing CLV

Do **not** build new infrastructure. In priority order:

1. **Fix the grading side first.** `graded_rows_available` = 0 for 7 of 8
   sports is upstream of everything else; settlement cannot match what does not
   exist. Work backward from `_graded_rows_for_date` per sport. Until this is
   non-zero, no settlement change can be evaluated.
2. **Then fix the key join.** The `unmatched_samples` payload already names the
   failure precisely (prop/totals records vs. a moneyline-only graded set) —
   this is a diagnosable mismatch, not a mystery.
3. **Independently of both — and this is the cheap win — CLV does not need
   settlement.** Closing price is known at the pregame→live transition, hours
   before any outcome. `odds_refresh_tracking` already stamps it. A job that
   joins the recommendation's own `quote` (opening) to `market_state`'s stamped
   close, keyed by market id, produces `clv_pct` with **no dependency on
   grading, outcomes, or `settle_result`**. That is the measurement the brief
   asks for, and it is reachable without touching the 367 MB chunk path at all.

Rule to hold: **unrecorded is unrecoverable.** The opening `quote` is being
written today. Do not let a ledger-size fix drop it.

---

## 4. Coverage vs. edge

**Different code paths, and the split is real but accidental.**

- **Projections** come from `attach_projections` (the 4-sport, 43-pair join).
  They render on every row the join can answer for. Every projection now carries
  `model_skill`, `unmeasured` is a first-class value, and a degeneracy detector
  reports any `(kind, market, segment)` collapsed to one value across ≥4 games.
  This part is in good shape.
- **Edges** come from two *other* paths: `recommendation_engine.filter_candidates`
  (the intelligence lane) and `layer2_board` (the published shortlist). Neither
  reads the projection layer's skill declaration.

### Is there a gate? Yes — but it gates price quality, not model skill.

`[measured, served shortlist 2026-08-14]`:

```
opportunities_considered  14166        returned            200
rows_beyond_game_cap       7557        rows_excluded_market 2003
rows_below_value_floor      742        min_value_pct       -2.0
```

The dominant filter is a **per-game cap**, then a market exclusion, and only
then a value floor. The floor itself is calibrated from the pool's own
per-family EV spread (1.25× the family's typical hold) — its own comment
records that at 2.0× it "REJECTED NOTHING ANYWHERE". It is a well-built junk-price
filter. **It is not, and does not claim to be, a measured-skill threshold.**

### Does every game get a pick? No — but most published rows have no model in them.

Of the 200 rows served: **57 carry `model_edge_pct`** — 28.5%.

| sport | rows | with model comparison |
|---|---|---|
| mlb | 84 | 55 (65%) |
| nfl | 14 | 2 (14%) |
| wnba | 12 | **0** |
| soccer | 90 | **0** |

143 of 200 published opportunities are ranked on market-derived EV alone. And
**31 of the 57 model comparisons are negative** — the board publishes rows where
its own model disagrees with the market in the wrong direction.

### What a model with no signal outputs

Two answers, and one of them is bad:

- **The projection layer refuses.** `wnba_projections` drops
  double/triple-double rather than invent P(over) from a mean;
  `nfl_game_projections` refuses spread probabilities because the board's
  `line: 6.5` carries no side; `prop_projections` returns `None` on
  whole-number lines. These are correct and well-argued.
- **`recommendation_engine._fair_probability` invents one.** The fallback chain
  is `fair_probability → model_probability → confidence → score/100 → **0.5**`.
  A candidate with no model probability at all is treated as a coin flip; and
  `confidence` (a scoring artefact) is silently consumed as if it were
  P(outcome). Against a plus-money side, a 0.5 default manufactures a large
  edge that then clears a threshold of 0.0. `[from-code]`

### The vig error is fixed in one layer and live in the other

`#238` established that comparing a model probability to a raw book price
overstates edge by roughly half the hold (median hold 6.25% → ~3.1 points).
`prop_projections`, `nfl_game_projections`, `soccer_projections` and
`quote_enrichment` were all fixed and label their output
(`edge_priced_against: "no_vig_fair"`).

`recommendation_engine._repriced_probabilities` was not. It computes
`implied_probability = _parse_american_odds(current_odds)` — the **raw, vigged**
price — and `filter_candidates` passes that straight into `calculate_edge`,
overriding anything the candidate carried. Every edge on that lane is
systematically optimistic by about half the hold, and the gate it is compared
against is 0.0. `[from-code]`

### The gate's adaptive machinery is inert

```python
threshold = min_edge + policy_spec.min_edge_bias          # 0.0 + 0.0 (balanced)
if market_sample >= 3 and market_roi < -0.04:   threshold += ...   # market_sample = 0
if market_sample >= 3 and calibration_error > 0.18: threshold += ...# market_sample = 0
if reliability_multiplier < 0.88:               threshold += 0.01  # = 1.0 exactly
```

`market_sample` is `build_reliability_profile(...)["sample_size"]`, which is
`settled_count`. Settled count is **0** across every sport and market
`[measured]`. With no settled history, `win_rate` and `roi` are `None`,
`calibration_error` is 0.0, and `reliability_multiplier` computes to exactly
1.0. Every branch is dead. All callers use the `min_edge=0.0` default.

**The effective published rule is: any positive edge, measured against a vigged
price, from a fair probability that may be a hard-coded 0.5.** This is finding
(2) in full, and it resolves to finding (1): the gate cannot adapt because
nothing has ever settled.

---

## 5. Devigging

**Five implementations. All multiplicative. Three different
aggregate-then-devig orderings, live simultaneously.**

| implementation | method | scope |
|---|---|---|
| `opportunity_signals.devig` | multiplicative (default) / power (available) | n-way, any market |
| `prop_projections._no_vig_over_probability` | multiplicative | 2-way + 3-way, on **consensus** |
| `soccer/market_anchoring.devig_decimal_odds` | multiplicative | decimal, n-way |
| `hockeysim.devig_two_way_home_prob` | multiplicative | 2-way only |
| `build_soccer_picks._devig` | multiplicative | n-way |

No Shin, no additive. `power` is implemented, documented as the better choice
for props (a +390 and a −450 side are routinely one market), and **called by
nothing** — every call site takes the multiplicative default. `[from-code]`

### Three-way handling is right

Both `opportunity_signals.devig` and `_no_vig_over_probability` require every
leg and refuse rather than de-vig across two of three. `soccer_projections`
declines to price 3-way h2h at all with a stated reason. This class of error —
which "manufactured 7 of the 10 arbitrages the first measurement pass
reported" — is closed.

### The inconsistency that matters

`opportunity_signals` states the rule explicitly: *de-vig within a single book,
then aggregate* — because normalising a best-over-here / best-under-there pair
"silently launders a line-shopping edge into the fair price". Its
`consensus_fair_probability` does exactly that: per-book multiplicative devig →
**median** across books → renormalise.

`book_grid`'s `consensus[side]` does the opposite order: **mean of implied
probabilities** across fresh books per side → convert back to an American price.
`prop_projections._no_vig_over_probability` then de-vigs *that*.

So the same board carries two fair values built by different orderings and
different central statistics (median vs. mean):

- `layer2_board` / `odds_book_quotes` → per-book devig, median
- board projections' `edge_vs_market_pct` → mean-of-implied, then devig

These are not equal in general, and the gap widens exactly where books disagree
— which is where edge is supposed to be. **Fix this before any CLV number is
compared across sports**, because the two orderings are unevenly distributed
across the projection producers.

### Book weighting

None. Books are unweighted; the choice is median-vs-mean only. The reasoning
for median is sound and stated (11 books of wildly different quality, no sharp
anchor — no Pinnacle, Circa or exchange in the feed). Worth recording as a
structural limit: **with no sharp book in the feed, "the market" is a consensus
of soft books, and CLV against it will be systematically easier to beat than
CLV against a real close.** Any future CLV number needs that caveat attached.

---

## 6. Cost linkage

### Which sports drive artifact bytes `[measured 2026-08-14, /api/ops/artifacts/export?names_only=1]`

7,185 hot artifacts, **6.63 GB** total.

| sport | files | MB | % bytes |
|---|---|---|---|
| **mlb** | 4,514 | **5,696.9** | **86.0%** |
| wnba | 1,814 | 363.2 | 5.5% |
| reports | 17 | 280.9 | 4.2% |
| soccer | 517 | 155.5 | 2.3% |
| nfl | 23 | 78.9 | 1.2% |
| settlement_inputs | 64 | 30.0 | 0.5% |
| nba | 150 | 19.1 | 0.3% |
| nhl | 86 | 1.7 | 0.0% |
| ncaaf / ncaab | — | 0 | 0% |

The 11.6 MB tail from the first-byte sample does not just cluster by sport — it
**is one sport**, and within it, one family:

| family | files | MB | % of all bytes |
|---|---|---|---|
| mlb book_quotes | 18 | 1,661.5 | 25.1% |
| mlb odds_history | 36 | 1,420.5 | 21.4% |
| mlb ladders | 100 | 1,272.1 | 19.2% |

**Odds capture is 65.7% of the platform's bytes and is ~97% MLB**
(`book_quotes`: mlb 1,661 MB, nfl 58, wnba 57, soccer 34). Individual days:
`mlb_source/tracking/book_quotes/2026-08-07.jsonl` = **329.5 MB**.

`reports/intelligence` at 280.9 MB across 17 files is the evaluation-ledger
bloat from §3 showing up in the egress budget too.

### What sets sweep cadence today

Cadence **is** sport-aware, in two ways `[from-code]`:

- `_PREGAME_SWEEP_INTERVAL_DEFAULTS = {"soccer": 8h}`, fallback **2h** for
  every other sport, overridable per sport via
  `SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_<SPORT>`.
- `_apply_pregame_sport_cadence` drops a sport mid-interval when *its own*
  games are not live — added because "WNBA re-swept every 60s for the whole of
  an MLB slate".
- Live phase 60s; off-hours ceilings 3600s (dead) / 900s (game day).

**But the cadence is set by liveness and by byte cost, not by line-movement
speed or measured edge.** Soccer's 8h is a cost decision; the 2h fallback is a
default. Nobody has measured how fast each sport's lines actually move.

### The tension the brief names, made concrete

`book_quotes` and `odds_history` are simultaneously (a) 46.5% of all bytes and
the obvious thinning target, and (b) **the only record of line movement**, which
is what `build_market_history_view`, the steam detector, `movement_velocity`,
and — critically — **any future CLV computation** read. The off-hours game-day
ceiling comment already says this in as many words: 900s exists so that pregame
gives "a meaningful pregame trajectory, not just an open and a close".

So the ordering is forced: **measure CLV first (§3), then thin.** Thinning
before CLV exists removes the evidence needed to justify the thinning, and the
sport carrying 86% of the bytes (MLB) is also the only sport with a measured
model. Do not thin MLB odds capture on byte cost alone.

---

## 7. Ranked fixes — most load-bearing first

Each is a separate lane. None of this pass changed code.

**1. Make CLV computable without settlement.** Join the recommendation's own
`quote` (opening) to `market_state`'s stamped `closing_price`, keyed by market
id. No dependency on grading, outcomes, or the 367 MB chunk path. This is the
one measurement that unblocks §4's threshold, §6's cadence decision, and every
"where should modelling effort go" question. Everything else on this list is
worth less until it exists.

**2. Fix the grading side.** `graded_rows_available` = 0 for 7 of 8 sports.
Until it is non-zero, no settlement change can be evaluated and no ROI/win-rate
number can exist. `unmatched_samples` already names the key mismatch.

**3. Stop the recommendation lane pricing edge against vigged odds.**
`_repriced_probabilities` → raw `_parse_american_odds`. `#238` is fixed in four
other modules and live here. One-line class of change; large and systematic
effect on what gets published.

**4. Kill the 0.5 fallback in `_fair_probability`, and stop reading `confidence`
as a probability.** A candidate with no model probability should be *excluded*,
not treated as a coin flip. Same file, same lane as (3).

**5. Pick one devig ordering and one central statistic.** `book_grid`'s
mean-of-implied vs. `opportunity_signals`' per-book-devig-then-median. The
latter has the better documented argument. Until this is one function, CLV is
not comparable across sports — which makes (1)'s output ambiguous.

**6. Fix the soccer backtest leakage.** `_load_team_ratings` computes one
rating set from the full season and applies it to matches inside that season.
Give `compute_team_ratings` a required as-of date and make the caller pass the
match date. Retire or re-run `data/soccer_source/*/validation/*_backtest_*.csv`;
until then those numbers should not be cited.

**7. Split the MLB prop de-bias fit from its scoring window,** and **deploy
`mlb_prop_calibration`.** It is committed (`aac18260`) and **absent from the
deployed tree** (`f9aa2399`) — the only MLB skill numbers in existence are not
being served, so every MLB prop row on the live board still reads `unmeasured`.

**8. Extend the archive-replay harness to the remaining producers.** The
pattern (read the published artifact for date D, join to the outcome) is
correct, point-in-time-safe by construction, and portable. Order by board
presence: soccer pregame markets (90 of 200 published rows, 0% model
comparison), then WNBA props, then MLB pitcher props, then NHL and NBA.

**9. Turn on the shadow candidate ledger.** Off by default, wired, bounded,
sampled. Filter precision — how good were the candidates we rejected? — is
still structurally unmeasurable without it, and (1) is what makes its records
worth grading.

**10. Only then, revisit sweep cadence per sport.** Measure line-movement speed
per sport first. MLB is 86% of bytes and the only sport with a measured model;
thinning its odds capture before CLV exists destroys the evidence.

---

## Open / unverified

- MLB sim feature as-of-ness is **UNKNOWN**, not clean — the backtest is PIT-safe
  by replay, which says nothing about the model's own inputs.
- NBA / NHL / NCAAB feature point-in-time status **UNKNOWN** — no harness reaches
  them.
- NHL and soccer market-anchoring make those two engines' market-relative
  evaluation partly circular. Quantify before believing any CLV number for them.
- refresh-worker's deployed commit was **not** re-read this session. The
  `mlb_prop_calibration` absence is confirmed for **web** only.
- Local HEAD `0a18d901` has diverged from deployed `f9aa2399`.
