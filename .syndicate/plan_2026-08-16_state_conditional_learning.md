# Plan — state-conditional learning (pace, events, game shape) — 2026-08-16

> **Question asked:** build skills/automation that take each sport's pregame model
> (games + props) and live model (games + props) and learn greater accuracy from
> **pace, game events, and game shape**. Start MLB and WNBA; soccer and NFL/NCAAF
> are close behind.
>
> **Companion, not replacement:** `docs/reports/syndicate_learning_loop_plan_2026_08_03.md`
> answers *is the model right on average*. This plan answers *when* it is right.
> Those need different primitives, and the old plan builds none of the new one.
> Every claim below is tagged `[from-code]`, `[measured]`, or `[NOT established]`.

---

## 0. The finding that reorders everything

**The conditioning variable is not written down anywhere.** Not "it is thin", not
"it is stale" — it does not exist as a record.

- MLB's live-lens JSONL persists game shape as a **rendered string**:
  `"liveText": "Top 5 | 1-1, 0 out | Colton Cowser vs Freddy Peralta"`, plus
  score and status. `[measured 08-16 from data/mlb_source/source_artifacts/data/live_lens/live_lens_2026_08_16.jsonl]`
- `live_gameline_ledger` v2 (built 08-16, the newest and best-shaped store) records
  `game_state`, `home_score`, `away_score` — a status word and a scoreline.
  `[from-code, live_gameline_ledger.py:198-200]`
- WNBA's live context artifact is card-shaped: `odds`, `betting`, `sim`,
  `prop_recommendations`. No period, no clock, no possessions.
  `[measured 08-16 from data/live/wnba_cards_context_2026-06-16.json]`
- `basketball_props_features.NUM_COL_MAP` is box-score totals — PTS/REB/AST/MIN.
  **No pace, no possessions, no tempo.** `[from-code]`

So: no per-sport model in this repo can currently be scored by state, because no
join key for state is persisted. That is the whole gap, and it is upstream of
every modelling idea in this plan.

### And the fix for MLB is nearly free, which decides the sport order

**MLB's game-shape vector already exists, fully populated, at tick time, and is
discarded.** `vendor/mlb_bettingv2/sim_engine/live_mc.py:20` `LiveSituation`
carries `inning, top, outs, bases, away_score, home_score, runner_on_1b/2b/3b,
balls, strikes, current_pa_pitch_count, pitcher_pitch_count,
pitcher_batters_faced, pitcher_entered_mid_inning`. `[from-code]`

It is constructed on every live tick to feed `estimate_live` (120 sims/live game,
on live-odds-worker) and then thrown away. `[from-code, live_gameline_join.py
docstring; production-confirmed 08-15 at `live_mc: 6`]`

**Base-out × inning × score-differential is the classic run-expectancy grid** — a
conditioning structure baseball solved decades ago, ~200 cells, discrete and
low-dimensional. We do not have to invent MLB's state space; we have to
`json.dumps` it.

---

## 1. What already exists (do not rebuild any of this)

| Piece | File | State |
|---|---|---|
| CRPS / pinball / Brier / reliability / bias-dispersion | `shared/model_scoring.py` | **built, mostly dark** — only `binary_calibration_metrics` has a live caller `[from-code]` |
| Versioned calibration profiles (load/save/override) | `shared/calibration_profile_store.py` | **built, ZERO non-test callers** `[from-code]` |
| Rolling-window drift detection | `shared/drift_detection.py` | wired at `intelligence_evaluation.py:2392` `[from-code]` |
| One grading contract + per-sport grader registry | `shared/graded_outcomes.py` | wired into `evaluation_settlement.py:27-28` `[from-code]` |
| Full-pool (rejected-candidate) ledger | `shared/shadow_candidate_ledger.py` | one gated caller, `intelligence_state.py:4280` |
| CLV open-half capture | `clv_opening_ledger.py`, `clv_join.py`, `live_gameline_ledger.py` | built; live ledger is v2 as of 08-16 |
| Model/skill provenance | `projection_skill.py`, `model_version.py` | live on both services `[measured 08-14]` |
| The **only** online parameter update in the repo | `shared/basketball_props_calibration.py` | 7-day rolling **mean shift per stat**, `min_pairs=50`, plus per-player. **No dispersion, no segmentation, no hold-out.** `[from-code]` |
| Settlement cost preflight | `scripts/settlement_cost_preflight.py` | built |

**Read this table as good news.** Roughly two-thirds of the machinery this plan
needs is already written and merely unreachable. The work is wiring and one new
primitive, not a build.

---

## 2. Blockers on the outcome side, verified

These make the *right-hand side* of every join empty. Nothing below Phase 1
produces a number until they are cleared.

1. **MLB grading is pinned at ONE ROW A DAY, and the cause is a path.** Freeze
   writer and grading reader sit on two trees one segment apart; `ml` graded rows
   = exactly 1 on all 8 dates checked. **Fix is built and tested (419 passing, 3
   new tests verified non-vacuous) and NOT DEPLOYED** — runbook at
   `.syndicate/handoff_deploy_freeze_reader_tree.md`. `[measured 08-16 ~18:2xZ]`
2. **The settlement autorun is off**, and `/api/ops/evaluation-settlement/status`
   serves a **stored file** — it read `2026-08-06T11:03:17Z`, ten days stale.
   Check `epoch` before quoting it; this lane has already been opened once on that
   wrong premise. `[measured 08-16]`
3. **Precision floor.** MLB live MC = 120 sims → SE ±4.56 pp at p=0.5; production
   basketball `n_sims` = **100** (engine default 2000) → ±4.3 pp at p=0.25.
   `[measured 08-15]` This is the hard constraint on Phase 2 — see §6.
4. **WNBA game lines are not measurable yet.** `pred_margin` starts 2026-08-02;
   9 of 361 completed games carry one; n=30 due **~2026-08-26**. `[measured 08-14]`
   → WNBA's Phase-2 target is **props**, not game lines, until that date.

---

## 3. Phases

### Phase 0 — unblock the outcome side (days; blocks everything)

- Deploy the freeze-reader-tree fix per the existing handoff. One change, measured,
  logged to `deploys.md`. Expect MLB `ml` graded rows to go 1/day → slate-wide.
- Run `scripts/settlement_cost_preflight.py` and take the autorun decision **with
  the cost number in hand**. The standing objection (`matched: 0`, spends memory
  for nothing) was measured *before* the path fix and must be re-taken after it.
- **Exit:** MLB graded rows > 1 for a date; `graded_rows_for_date` non-empty for
  MLB **and** WNBA on the same date.

### Phase 1 — the missing primitive: a game-shape record (the new work)

**One contract, `syndicate/features/shared/game_shape.py`.** A per-sport extractor
returning a flat, JSON-safe dict, plus a bucketing function. Written at tick time
by the loops that already run, appended to the **existing** `live_gameline_ledger`
record — not a new store. (Three disagreeing outcome stores is a documented
failure mode of this repo; do not make it four.)

Fields, chosen because the source is already in hand at tick time:

| sport | fields | source |
|---|---|---|
| **MLB** | inning, half, outs, base_state (8 states), score_diff, batting_team, pitcher_pitch_count, pitcher_batters_faced, times_through_order, entered_mid_inning, balls/strikes | **`LiveSituation`, already constructed** `[from-code]` |
| **WNBA/NBA** | period, seconds_remaining, score_diff, possessions_elapsed → **pace**, team_fouls/bonus, starters_on_floor | box/live feed behind `basketball_live_artifacts` — **needs a possession count; this is the one real new derivation** |
| **Soccer** | minute, score_diff, red_cards per side, shots/SOT accumulated, phase (score-effects band) | `poll_league` live state; files exist per league (`api/live_state/`) but the sampled one was `count: 0` `[measured 08-16]` |
| **NFL/NCAAF** | quarter, clock, down, distance, field_position, score_diff, possessions_remaining, `pace_secs_play`, timeouts | `football/features/pace_features.py` + drive priors already read these `[from-code]`; nflverse pbp now lands `[measured 08-16 18:31Z, #441]` |

**Non-negotiables carried from the ledger:**
- Dedupe on movement, bound per build and per file, and **say so in the counters
  when it truncates** — copy `live_gameline_ledger`'s discipline verbatim.
- Env kill switch, default on. Worker periodic work is never free (`#241` caused a
  production restart loop; ~1.4 GB headroom on refresh-worker).
- Disk-backed under `data/<sport>_source/`, never `reports/**` (8 MB keyvalue
  ceiling).
- **Capture is decoupled from learning.** Turn capture on for all five sports as
  soon as it is written, including sports whose models are not ready to learn. A
  week not recorded can never be learned from, and NCAAF opens **2026-08-29**,
  NFL ~**09-10**.

**Exit:** one date's ledger for MLB and WNBA where every record carries a
`game_shape` block and a bucket label, with a non-zero count per bucket printed.

### Phase 2 — score by state

`state_conditioned_scoring`: join `(game_shape, model prob/mean, market fair prob,
outcome)` and compute, **per bucket**, using `model_scoring.py` as-is:

- **bias and dispersion separately.** "We are 0.3 runs high" and "our σ is 20% too
  tight" need opposite fixes and one MAE cannot tell them apart. This is also the
  metric that survives the precision floor (§6).
- CRPS / pinball on continuous projections — no bet and no settlement required, so
  it is thousands of observations a night instead of dozens a week.
- Brier + reliability on binary probabilities, **and the market's Brier on the same
  rows**. A model number without the market's number beside it is not a result;
  soccer is the standing proof (multiclass Brier **0.5875 vs 0.5737**, worse in 8
  of 9 leagues, p = 0.039 `[measured 08-15]`).
- **Empirical-Bayes shrinkage toward the sport × market parent.** Slicing by state
  is precisely what makes cells thin; shrinkage is what makes a thin cell degrade
  instead of overfit. This is not optional polish.
- **Every cell reports n, and a cell below the floor reports `unmeasured`, not a
  number.** `projection_skill` already treats `unmeasured` as first-class — follow
  that precedent rather than inventing a second convention.

### Phase 3 — feed it back, calibration first

Two channels; keep them separate and never confuse one for the other.

- **(a) Calibration** — a post-hoc per-bucket mapping applied to the model number
  *before* the edge is computed. Cheap, reversible, no sim change. Ship through
  `calibration_profile_store` (built, dark). **Start here and only here.**
- **(b) Model change** — refitting sim parameters. Slow, needs a hold-out, and is
  Stage 3 of the 08-03 plan. Not in scope until (a) has run a full promotion cycle.

**Shadow-then-promote, never auto-apply.** A candidate profile is promoted only if
it beats the incumbent on **hold-out** CRPS *and* does not regress calibration,
with a minimum-n gate and a variance-aware margin. Same gate shape every sport.
The existing basketball loop is the counter-example to learn from: it applies a
mean shift on every run with **no hold-out check that the shift helped**.

### Phase 4 — pregame ↔ live coupling ("game shape overall")

The question no current instrument can answer: **is the live model's error its
own, or is it inheriting the pregame model's?** If pregame error predicts live
error at the same state, the live model needs no state work at all — the pregame
prior needs fixing, and state-conditioning would be chasing a shadow.

Requires the pregame freeze and the live ledger keyed the same way. Both exist
after Phase 0 + Phase 1, and not before. **Do not attempt this earlier** — it is
the single most attractive wrong turn in this plan.

---

## 4. Sport order, with the reason attached

1. **MLB.** State vector already built (`LiveSituation`); state space already
   solved (run-expectancy grid); actuals richest; the join is `batter_id`, an
   exact id join with none of `#218`'s name-matching failure; and the prop bias is
   **already measured** — biased, not blind: every counting market carries real
   signal and loses to a constant baseline by sitting high; de-biasing flips 5 of 7
   `[measured 08-14]`. The calibration target is known before the work starts.
2. **WNBA — props now, game lines after ~08-26.** The only online calibration loop
   in the repo already lives here, so this is *segmentation of an existing loop*,
   not construction. Game lines are n-blocked until 08-26.
3. **NFL / NCAAF — capture only, immediately, on date pressure.** NCAAF opens
   08-29. Phase 1 capture must be live before the openers; Phase 2 waits for volume.
   Note NCAAF has no game today (`layer1?sport=ncaaf` → `games=0`), so capture
   cannot be verified end-to-end until the season.
4. **Soccer — capture now, learn last, and say why.** The model **loses to the
   market** and its errors sit on the **favourites**, so published `model_edge_pct`
   would systematically point edges at underdogs `[measured 08-15]`.
   **State-conditional learning cannot rescue a model that is behind on the mean.**
   Fix the level first (that is the `soccer-model-coverage` lane's work); capture
   state in parallel because capture is cheap and the season is running.

---

## 5. The skills / automation layer — what to actually build

Four artifacts, matching patterns this repo already uses.

**S1. `/model-learn <sport>` — `.claude/commands/model-learn.md`.** The weekly
loop as a brief, in the shape of `model-audit.md`: print per-family date coverage
and the intersection **first** (CLAUDE.md's standing trap — a backtest can look
like months and rest on one date), then the per-bucket reliability card, then a
candidate calibration profile written to `.syndicate/`. **Read-only on the model.
It proposes; it never promotes.**

**S2. `/state-coverage <sport>` — the denominator gate.** Answers "how many
observations does each bucket actually have" and refuses to print a rate where
n is below the floor. This exists because *"a rate, not a count"* is already a
standing rule here — five wrong findings in one session came from missing
denominators.

**S3. A scheduled refit job**, documented as `.syndicate/scheduled_task_model_refit.md`
in the same shape as `scheduled_task_branch_overlap.md` / `_clamp_watch.md` /
`_oom_band.md`. Weekly, refresh-worker, bounded, emits a candidate profile + a
report and **nothing else**. Promotion stays a human decision through S1.

**S4. Accuracy gate in `/preflight`.** `migration_gate.py` checks structure and
parity, not skill — a sim change can ship today with zero evidence it improved
anything. Add a frozen-fixture backtest that fails on material CRPS/calibration
regression.

---

## 6. Refusals — read before writing code

- **Do not slice by state before deciding what the sample can support.** At 120
  sims (MLB live) and 100 sims (basketball), per-cell *win probability* is noise
  with a decimal point — and the noise does **not** average out, because
  `estimate_live` is seeded `seed=int(gamePk)`, making the error a
  state-correlated bias rather than tick-to-tick jitter `[from-code]`. Score the
  **bias/dispersion** side, which is robust to estimator noise in a way per-cell
  Brier is not, or raise sims for the scored population only.
- **Do not build a second outcome store.** Extend `live_gameline_ledger`.
- **Do not publish a state-conditioned number without its n and the market's number
  beside it.**
- **Do not credit the loop with an improvement without a hold-out.** A mean shift
  applied and then measured on the same window will always look like it worked.
- **Do not read `data/**` in the checkout as production.** Per-family windows do
  not line up; four MLB families intersected to **one usable date** `[measured
  08-05]`. Production has far more history than the checkout — 81 WNBA dates vs
  "4 files" locally `[measured 08-14]`.
- **`_SCORE_SIM_WEIGHT` is 0.0**, so `sim_component` is exactly 0.0 on main
  markets too `[measured 08-16]`. Nothing is sim-ranked today. Any claim that
  better sim accuracy moved the board is false until that weight is non-zero —
  worth knowing before attributing a board change to this work.

---

## 7. Proposed todo IDs (next free is `#447`; `#446` is the highest in use)

| id | item |
|---|---|
| `#447` | Deploy the freeze-reader-tree fix; re-take the settlement-autorun decision on post-fix numbers (Phase 0) |
| `#448` | `shared/game_shape.py` + MLB extractor from the existing `LiveSituation`; persist into `live_gameline_ledger` (Phase 1) |
| `#449` | WNBA/NBA game-shape extractor incl. a possession count (pace) — the one genuinely new derivation |
| `#450` | NFL/NCAAF + soccer game-shape capture, **capture only**, before the 08-29 opener |
| `#451` | `state_conditioned_scoring` over `model_scoring.py` with EB shrinkage and an `unmeasured` floor (Phase 2) |
| `#452` | Per-bucket calibration profiles through `calibration_profile_store`, shadow-then-promote (Phase 3a) |
| `#453` | Skills S1–S4 |

**Lane names reserved by this plan and deliberately NOT opened** (no session holds
them): `game-shape-capture`, `state-conditional-scoring`, `calibration-promotion`.
Whoever takes one must `/lane open` it and take the files itself.
