# Syndicate Learning-Loop Assessment + Plan — 2026-08-03

> Question asked: *what piping exists so every sport gets more accurate over time, both
> as a simulation/model and as a betting operation — and what would make it best in class?*
>
> This is a static-code + artifact audit with file references, plus a staged plan.
> Where a claim depends on production state it is labelled and sourced.
> Companion to `syndicate_end_to_end_assessment_2026_08_02.md` (forward pipeline);
> this doc covers only the **backward** pipeline.

---

## 1. What exists today

There are three independent loops. Only one of them is actually closed and running.

### Loop A — betting-outcome loop (cross-sport, Layer 2). Wired, carrying zero data.

| Stage | Where | State |
|---|---|---|
| Record | `pipeline/intelligence_state.py:1301` `maybe_record_board_state_to_evaluation_ledger` → `intelligence_evaluation.record_prediction/record_recommendation` | Gated on `SYNDICATE_INTELLIGENCE_LEDGER_RECORDING_ENABLED` (refresh-worker only). Fingerprint-guarded per `(date, board fingerprint)`. |
| Store | `reports/intelligence/evaluation_ledger_chunks/<date>.jsonl` | Chunked JSONL, one chunk per date, index + manifest sidecars. |
| Settle | `syndicate/features/shared/evaluation_settlement.py:277` `settle_ledger_for_date` | Autorun ON (`render.yaml:296`, 6h interval). **Covers MLB + WNBA only** (`_SUPPORTED_SPORTS`, line 33). |
| Measure | `intelligence_evaluation.compute_metrics` / `build_reliability_profile` (1230) | win rate, ROI, line CLV, price CLV, calibration MAE + Brier → one scalar `reliability_multiplier ∈ [0.78, 1.06]`. |
| Act | `recommendation_engine.filter_candidates` (1002) dynamic min-edge; `rank_recommendations` (1225) `adjusted_score`; `select_policy` / `compare_policies` promotion; `bankroll_manager.compute_board_stake` fractional Kelly shrunk by `_sample_credibility(settled_sample_size)` | All live on the board path (`pipeline/intelligence_state.py:2719` → `intelligence.rank_candidates`). |

**Production status:** ledger holds **zero recommendation records**. Confirmed 2026-08-04T03:37Z
after a forced settlement cycle (`todo.md`, "OPEN 2026-08-04 (2)"): `total_recommendation_records: 0`.

Consequence chain, all currently true in production:
`reliability_multiplier ≡ 1.0` for every sport and market → the dynamic min-edge in
`filter_candidates` is inert → `calibration_error`/`roi` terms in `rank_recommendations`'
`core_adjusted_score` are all `0.0` → `compare_policies` returns all-zero rows → policy
promotion never fires → Kelly stakes pinned at the `_sample_credibility` zero-evidence floor.

**The board ranks well; it does not learn at all.**

### Loop B — model-calibration loop (per sport). One real instance out of eight.

- **Basketball props (NBA/WNBA) — genuinely closed and automatic.**
  `shared/basketball_props_calibration.py` computes a 7-day rolling prediction-vs-reconciliation
  bias per stat (`compute_biases`, `min_pairs=50`) plus per-player biases, applied inside
  `basketball_props_predictions.py:212-240` on every run and persisted as
  `props_calibration_<date>.json`. This is the only online parameter update in the repo.
  Limits: mean-shift only (no dispersion/spread calibration), no shrinkage beyond the
  pair-count floor, no hold-out check that the shift helped.

- **Everything else is a frozen constant fit once, by hand, offline.**
  - `football/sim_engine/smartsim2/calibration_profile.py` — NFL profile is *all multipliers
    1.0 by construction* ("reproduces today's hardcoded constants exactly"). NFL has never
    been calibrated through this seam. `ncaaf_calibration_profile.py` has real fitted numbers.
  - `soccer/sim_engine/soccersim/calibration_profile.py` + `league_profiles.py` — 10 leagues,
    fit against one-off truth baselines (the `soccersim_*_truth_baseline_report.md` series).
  - `nhl/sim_engine/hockeysim/calibration_profile.py` — self-documented as "exactly the
    defaults the absorbed engine shipped with"; the Phase 3 truth-layer deltas were
    computed (`hockeysim_phase3b_calibration_report.md`) but never written into the profile.
  - **MLB has no parameter-level recalibration loop at all**, despite owning the richest
    actuals in the repo (`mlb/market_accuracy.py`, `mlb/live_lens_daily_accuracy.py`, the
    reconciliation actuals writer).
  No script re-fits any of these. No schedule, no CI job, no drift check. They decay silently
  across a season and nothing notices.

- **A second, parallel outcome store that talks to nobody.**
  `prediction_ledger.py` + `prediction_reconciliation.py` have their own autorun
  (`render.yaml:268`, 24h) writing a separate ledger with its own CLV, ROI and signal-weight
  logic. It is not read by `evaluation_settlement`, `build_reliability_profile`, or the ranker
  — except as a fallback row count in `performance_summary.json`.

### Loop C — offline backtests. Real, but manual and one-shot.

`scripts/backtest_nfl_injury_adjustment.py`, `backtest_soccer_live_lens.py`,
`backtest_soccer_starter_awareness.py`, `build_hockeysim_truth_baseline.py`,
`backfill_nfl_performance.py`, `backfill_smartsim2_performance.py`, and ~50 calibration
reports in `docs/reports/`. None is scheduled, none gates a deploy, none feeds a profile
automatically. `.github/workflows/` has `ci.yml` + `daily-update.yml` and no accuracy job.

### Per-sport grading coverage (the input side of everything above)

| Sport | Graded actuals module | Reachable by settlement |
|---|---|:--:|
| MLB | `mlb/market_accuracy.py`, `live_lens_daily_accuracy.py` | ✅ |
| WNBA | `market_accuracy.py`, `live_game_accuracy.py`, `live_prop_accuracy.py` | ✅ |
| NBA | same four modules as WNBA | ❌ not in `_SUPPORTED_SPORTS` |
| NHL | `market_accuracy.py`, `live_game_accuracy.py`, `live_lens_daily_accuracy.py` | ❌ |
| NFL / NCAAF | `smartsim2_performance_tracking.py`, `smartsim2_betting_performance.py` | ❌ |
| NCAAB | none | ❌ |
| Soccer | **none** — no actuals builder, no reconciliation dir | ❌ |

---

## 2. Why this can't reach best-in-class as designed

Nine structural problems, roughly in order of leverage.

**P1. The loop carries no data.** Everything downstream is arithmetic on an empty set. Until
`total_recommendation_records` is non-zero, no amount of new machinery changes an outcome.

**P2. Three outcome stores, no shared grading contract.** Evaluation ledger, prediction
ledger, and per-sport accuracy modules each define "what happened" differently. That is
exactly why settlement reaches 2 of 8 sports: each new sport needs a bespoke
`_<sport>_graded_rows_for_date` adapter (`evaluation_settlement.py:82-186`) shaped around
that sport's own artifact.

**P3. Outcome-only, no counterfactual.** Only candidates that were *published to the board*
are recorded. Every candidate the filter rejected is never graded — so the system can never
learn that its own filter is wrong, only that the bets it made won or lost. The set you learn
from is selected by the policy you are trying to evaluate.

**P4. Learning granularity is one scalar per sport (and a same-shaped one per market).**
`reliability_multiplier` collapses calibration, win rate and ROI into a number bounded to
±22%. `_market_profile` (`recommendation_engine.py:993`) recomputes the identical function
scoped to a raw market string. There is no calibration *surface*: nothing per line-band, per
confidence bucket, per book, per lead-time, per pregame-vs-live, per starter-known-vs-not.

**P5. The learning signal chosen is the slowest one available.** Binary win/loss on bets
taken needs hundreds of settled rows per segment to separate skill from variance (the
`DecisionPolicy` comment at line 40 already documents getting burned by exactly this at n=12).
Two far faster signals are unused or half-captured:
- **CLV** — dozens of times more sample-efficient than win rate, available on every bet
  immediately at kickoff.
- **Continuous distributional error** — CRPS / pinball loss of the sim's own distribution
  against the realized stat, on *every player and every game*, bet or no bet. This is
  thousands of observations per night per sport instead of dozens, and it measures the sim
  directly rather than through the market.

**P6. True closing prices are captured and then not used.** `odds_refresh_tracking.py:1385`
stamps `closing_line`/`closing_price` on `market_state` at the real pregame→live transition —
correct, idempotent, exactly right. But `evaluation_settlement.py:362,367` settles with the
*graded row's own* line and price instead, which is generally the price the bet was recorded
at. So `_price_clv` (`intelligence_evaluation.py:1152`) computes ≈0 by construction. Soccer
runs no live odds phase at all, so no close is ever stamped for it.

**P7. The experimentation layer cannot run an experiment.** `compare_policies` scopes rows by
`_record_matches_policy` — records actually *served under* that policy. But `select_policy`
returns the leader, and with empty history every policy scores `0.0`, so the incumbent
`balanced` wins the stable sort and the challengers never receive traffic, never accrue
samples, and can never be promoted. There is no exploration budget and no forced holdout.
Separately, `promotion_score` (line 918) mixes realized ROI with *average edge and confidence*
— a policy can be promoted for being confident rather than profitable — and carries no
variance term, so a score gap at `min_sample_size=50` is still mostly noise.

**P8. No drift detection, no decomposition, no alerting.** Nothing surfaces "MLB total-runs
sim has run 0.3 high for 10 days", "NHL SOG props are 8% over", or "our edge on NBA spreads
disappeared when the book changed". Model error is never decomposed into bias vs. dispersion
vs. market-disagreement.

**P9. Nothing gates a change on accuracy.** `scripts/migration_gate.py` checks structure and
parity, not skill. A sim change can ship with zero evidence it improved anything, and there
is no record of which model version produced which prediction.

---

## 3. The plan

Six stages. Stages 0–2 are the ones that actually change outcomes; 3–5 are what makes it
best in class rather than merely working. Each stage is independently shippable and each
leaves the system better than it found it.

### Stage 0 — Make the loop carry data (days, blocks everything else)

1. **Find why zero records reach the ledger.** The instrumentation is already in place:
   `BOARD_STATE_LEDGER_RECORDED selected_date=... recommendation_count=N` and
   `BOARD_STATE_LEDGER_SKIPPED_EMPTY` print via `print(flush=True)`, which does reach Render's
   collector. Read refresh-worker logs for those two lines before theorising further —
   `N` distinguishes "written but the settlement filter is wrong" from "handed an empty list".
2. **Fix the self-concealing fingerprint stamp** (`intelligence_state.py:1329`): never stamp a
   `(date, fingerprint)` as handled when zero records were written. A no-op that marks itself
   complete is why this failure survived multiple sessions.
3. **Fix the flat-vs-chunked write/read split** (`todo.md` "OPEN 2026-08-04 (3)"):
   `_append_evaluation_ledger_record` honours `_is_chunked_ledger_path` (true only for the
   exact default path) while `settle_ledger_for_date` always reads the chunk path. Every
   settlement test against a temp ledger passes vacuously today. Make both sides agree on
   path shape — this is what makes local reproduction possible at all.
4. **Pass settlement the real close.** Join to `market_state.closing_price/closing_line` from
   the odds-history shard (`odds_lifecycle._resolve_market_state_across_shards` already
   returns both) instead of the graded row's price. Without this, price CLV is permanently ~0
   and Stage 2 has nothing to stand on.

*Exit criterion:* `/api/ops/evaluation-settlement/status` reports non-zero
`total_recommendation_records` **and** non-zero `settled`, and `performance_summary.json`
shows a real `win_rate` and a non-null `clv_price`.

### Stage 1 — One grading contract for all eight sports (1–2 weeks)

The reason settlement covers 2 of 8 sports is that grading is per-sport-shaped. Fix the
contract, not the adapters.

1. **Define `GradedOutcome`** in `shared/` — a typed row: `(sport, date, event_id, market_id,
   selection, side, line, price, model_probability, model_mean, model_sigma, actual, result,
   closing_line, closing_price, settled_at, model_version)`. This is the single shape every
   sport's grader emits and every consumer reads.
2. **Adapter per sport, thin.** MLB and WNBA already produce equivalent rows; NBA/NHL have the
   modules (`market_accuracy.py`, `live_prop_accuracy.py`) and just need the mapping. NFL/NCAAF
   map from `smartsim2_performance_tracking.py`. Then delete `_SUPPORTED_SPORTS` — support
   becomes "has a registered adapter".
3. **Build the two missing graders:** `build_soccer_actuals.py` (soccer has none at all — this
   is the single biggest coverage hole, an entire calibrated 10-league engine that can never
   be scored) and NCAAB.
4. **Retire the second ledger.** Fold `prediction_ledger.py`/`prediction_reconciliation.py`
   into the same store, or make it an explicit read-only view. Two disagreeing sources of
   truth for "what happened" will cause a wrong conclusion eventually.
5. **Fix the ledger's structural cost while touching it** — records embed full manifest blobs
   (`intelligence_evaluation.py:452`), which is what produced the 4.9GB chunk directory. Store
   manifest *pointers*; keep `_load_chunked_ledger_records` date-windowed.

*Exit criterion:* every sport with a slate produces graded rows for that date, and a single
query returns settled outcomes across all eight.

### Stage 2 — Measure the right things (1–2 weeks, the highest-value stage)

Replace "did the bet win" as the primary signal.

1. **Shadow ledger over the full candidate pool.** Record and grade *every priced candidate*,
   including the ones `filter_candidates` rejected, with a `published: bool` flag. This is what
   makes the filter itself measurable and kills P3. Cost is small — the pool is already built.
2. **Scoring layer** (`shared/model_scoring.py`), computed per graded row:
   - **CRPS / pinball loss** for every continuous projection against its realized value —
     player props, team totals, spreads. This is the sim-quality metric, and it does not need
     a bet to exist. Thousands of observations per night per sport.
   - **Brier + log-loss + reliability curve** on binary model probabilities, binned.
   - **Bias vs. dispersion decomposition** — mean error and error/σ ratio separately. "We are
     0.3 runs high" and "our σ is 20% too tight" require completely different fixes and the
     current single MAE cannot distinguish them.
   - **CLV (price and line)** against the true stamped close from Stage 0.4.
3. **Promote CLV to the primary betting-quality metric** and the policy-promotion criterion.
   It converges orders of magnitude faster than ROI and it is available the moment a game
   starts rather than after grading.
4. **Replace the scalar with a calibration surface.** `build_reliability_profile` becomes a
   segmented lookup: `(sport, market_family, line_band, confidence_bucket, pregame/live)` →
   `{bias, dispersion_ratio, brier, clv, n}`, with **empirical-Bayes shrinkage toward the
   parent segment** so thin cells degrade gracefully instead of overfitting. The ranker,
   `filter_candidates`, and Kelly all read from this one surface.
5. **Recalibrate probabilities before they are priced.** Apply the fitted per-segment
   mapping (isotonic or Platt, refit nightly) to model probabilities at the point they enter
   the board, so the edge is computed against a *calibrated* number. This is the change that
   converts measurement into money.

*Exit criterion:* a per-sport, per-market reliability card with real n, CRPS, Brier, bias,
dispersion and CLV — and `adjusted_score` visibly moving because of it.

### Stage 3 — Automated recalibration of the sims (2–4 weeks)

Turn the frozen profiles into fitted artifacts. The seams already exist — `CalibrationProfile`
in football/soccer/hockey is precisely the right abstraction; it is just never refit.

1. **Profiles become data, not source.** Load `calibration_profile_<sport>_<version>.json`
   from the artifact root, with the current in-source constants as the versioned baseline and
   fallback. Preserves provenance and makes a rollback a file swap.
2. **Nightly/weekly re-fit job on the refresh-worker** (mirrors the existing autorun shape in
   `run_refresh_worker.py`): read graded rows over a trailing window → minimise CRPS +
   calibration error over the profile's tunable seams → emit a candidate profile + a report.
   Start with the parameters that already have documented calibration reports, so the fit can
   be validated against a known answer.
3. **Shadow-then-promote, never auto-apply.** A candidate profile runs in shadow for a fixed
   window; it is promoted only if it beats the incumbent on hold-out CRPS *and* does not
   regress calibration, with a minimum sample gate and a variance-aware margin. Same gate
   shape for every sport.
4. **Apply the deltas already computed and never shipped** — hockeysim Phase 3b, and give NFL
   its first real calibration (its profile is literally all 1.0s today).
5. **Extend the basketball props loop** from mean-bias to full distribution calibration
   (variance scaling + per-segment shrinkage), then generalise the same mechanism to MLB and
   NHL props, which have the sim output to support it and no loop today.

*Exit criterion:* at least three sports running on a profile that was fitted from settled
outcomes rather than hand-authored, each with a promotion record.

### Stage 4 — Real experimentation (2–3 weeks)

1. **Exploration budget.** Reserve a fixed share of the slate (say 5–10%, deterministically
   bucketed by event id) for the challenger policy regardless of its score. Without this,
   `select_policy`'s incumbent-wins-ties path guarantees a challenger never gets data. This is
   the single change that makes the existing policy machinery functional.
2. **Permanent hold-out.** A small fraction of candidates recorded and graded but never acted
   on, giving an unbiased baseline the acting policy cannot contaminate.
3. **Counterfactual replay harness.** Replay a stored candidate pool through an alternative
   policy/profile offline and score it against the same graded outcomes. Turns policy
   comparison from "how aligned were the bets we happened to make" (`_policy_alignment`, a
   heuristic proxy) into an actual counterfactual.
4. **Fix `promotion_score`:** drop `average_edge`/`average_confidence` from it (they are
   inputs, not results), lead with CLV, and add an uncertainty term so the margin scales with
   the standard error rather than being a fixed constant.

### Stage 5 — Guardrails and provenance (ongoing, cheap, do alongside)

1. **Model registry.** Stamp `model_version` (engine + profile version + code SHA) on every
   prediction and carry it into the ledger. Without it you cannot attribute an accuracy change
   to a code change, which makes every other measurement retrospective-only.
2. **Drift monitors + alerting.** Per sport/market rolling bias, CRPS and CLV with control
   limits; alert on drift, on zero-candidate days, on stale snapshots, and on settlement
   match-rate collapse. A settlement match rate that quietly falls to 20% looks exactly like
   "we made fewer bets".
3. **Accuracy gate in CI/deploy.** Extend `migration_gate.py` with a backtest that fails on
   material CRPS/calibration regression against a frozen fixture slate per sport.
4. **One accuracy surface in the app.** A single `/intelligence/accuracy` view: per sport and
   market — n, CRPS, Brier, reliability curve, bias, CLV, ROI, and the active profile version.
   The measurement layer needs to be visible or it stops being maintained.

---

## 4. Sequencing and rough effort

| Stage | Effort | Unblocks | Risk if skipped |
|---|---|---|---|
| 0 — data in the loop | days | everything | the whole learning stack stays decorative |
| 1 — one grading contract | 1–2 wk | 6 more sports | soccer/NCAAB/NFL can never be scored |
| 2 — right metrics | 1–2 wk | Stages 3 & 4 | learning stays 10–100× slower than it needs to be |
| 3 — auto recalibration | 2–4 wk | sim accuracy compounding | profiles keep drifting silently all season |
| 4 — experimentation | 2–3 wk | policy improvement | the policy layer stays permanently deadlocked |
| 5 — guardrails | ongoing | trust + attribution | regressions ship undetected |

Football season (NCAAF Aug 29, NFL ~Sep 10) argues for finishing Stage 0 and the
NFL/NCAAF half of Stage 1 before the openers — that is when the largest volume of gradable
outcomes starts arriving, and any week not recorded is a week that can never be learned from.

## 5. What "best in class" looks like at the end

- Every priced candidate on every slate in all eight sports is recorded, graded, and scored —
  whether or not it was bet.
- Model quality is measured continuously as distributional error (CRPS) against realized
  outcomes, not just as bet win rate, so a sport learns from thousands of observations a night
  instead of dozens a week.
- Betting quality is measured primarily as realized CLV against a truly stamped close.
- Probabilities are recalibrated per segment before the edge is computed, with shrinkage.
- Sim parameters are refit on a schedule from settled outcomes, promoted only through a
  hold-out gate, versioned, and rollback-able as a file.
- Policies compete on a real exploration budget with counterfactual replay and variance-aware
  promotion.
- Drift is alerted on, accuracy gates deploys, and every prediction is attributable to a
  model version.

---

*Sources: static read of `syndicate/features/shared/{intelligence_evaluation,evaluation_settlement,recommendation_engine,basketball_props_calibration,odds_lifecycle,odds_refresh_tracking}.py`,
`syndicate/features/{prediction_ledger,prediction_reconciliation,bankroll_manager}.py`,
per-sport `calibration_profile.py` modules, `pipeline/intelligence_state.py`,
`scripts/run_refresh_worker.py`, `render.yaml`, `.github/workflows/`, and
`docs/ai_context/todo.md` open items dated 2026-08-04. Production claims are sourced to the
todo entries that recorded them; nothing here was verified against Render in this session.*
