# MLB Sim Engine — Accuracy Assessment & Optimization Plan

- Date: 2026-07-16
- Scope: pregame + live modeling for game winners (ML), run lines, game totals, pitcher/hitter props; live game-shape tracking for live opportunities.
- Engine: `vendor/mlb_bettingv2/sim_engine` (pitch-level Monte Carlo) + `syndicate/features/mlb` (cards, live lens, accuracy surfaces).

---

## 1. What exists today (architecture assessment)

**Pregame.** `simulate.py` (~2,900 lines) is a genuine pitch-level MC: pitch model with count states, batted-ball type distributions, platoon/statcast shape multipliers, park/weather HR context, baserunning (1st-to-third, productive outs, ROE), manager model v2 (starter hooks by pitch count/TTO/leverage, reliever selection with leverage + availability), pitcher day-rate variance (`pitcher_distributions.py`), and mean-1 lognormal run-environment noise. Daily job runs 1,000 sims/game (`scripts/run_mlb_daily_sim_job.py` → `tools/daily_update.py --workflow ui-daily`); official locked-card publishing requires ≥250 sims. Probability calibration layer (`prob_calibration.py`) supports per-prop affine-logit / shrink-to-0.5 / tail-shrink, and forward tuning overrides gate at 2026‑04‑14 (`forward_tuning.py`). BvP matchup mode is currently **off** by default.

**Selection/policy.** Locked policy cards select by no-vig edge thresholds with per-submarket caps (e.g. hits cap 4, TB cap 6, HR cap 0, runs cap 1 with 10pt edge min), one-prop-per-player, and staking units. Promotion/backtest tooling exists (`backtest_totals_promotion.py`, `backtest_hitter_submarket_promotion.py`, dozens of `tools/tune/sweep_*` scripts).

**Live.** `live_mc.py` rebuilds exact game state (inning/outs/bases/count/lineup slot/pitch counts per pitcher) and re-runs the full sim — **default only 300 sims**. `live_prop_ranking.py` is a trained logistic (11 features: live edge, implied prob, current/pace gaps, progress, score diff…) with side priors blended in; one fitted artifact exists (`data/tuning/live_prop_ranking/default.json`, fit on ~1,772 settled live picks). Live lens builds per-game panels/segments, persists reports + JSONL logs + a live prop registry; settlement resolves actuals from archived `feed_live` boxscores by normalized player *name*.

**Accuracy surfaces.** `market_accuracy.py` (betting-card W/L/ROI by market), `live_lens_daily_accuracy.py` (live prop registry settlement), season eval (`run_season_eval.py` → ML brier/logloss/accuracy, totals MAE/RMSE/NLL, run-line brier, starter SO/outs MAE, F3/F5 segment error).

**Verdict on architecture: strong.** The simulation and tooling foundation is above par. The problems are (a) the measurement pipeline is mostly dark, and (b) the measured samples show specific, consistent calibration biases.

---

## 2. Measured accuracy (what data exists locally)

Only **5 days / 68 games / 122 starters** of `sim_vs_actual` evals exist locally (June 14–19, 2026, 1,000 sims/game). Season manifests aggregate to zero; all 18 locked-policy day cards on disk have **0 selections and 0 settled results**; the 2026-07-11 live prop registry has **0 entries**; season eval recap says "1 day, 0 games". This matches the known Render issue (`refresh_odds_sources.py` failing → stale odds → empty cards). **The scoreboard is broken; the engine is flying blind.**

From the 68-game sample (small — treat as directional):

| Market | Metric | Value | Read |
|---|---|---:|---|
| Moneyline | accuracy / Brier / logloss | 0.500 / 0.253 / 0.699 | Worse than the 0.25/0.693 coin-flip baseline on this sample. Sim-only ML is not beating anything yet. |
| Totals | MAE (runs) | 3.43 | High-ish; league-typical model MAE ≈ 3.0–3.2. |
| Run line (fav −1.5) | accuracy / Brier | 0.618 / 0.238 | Promising, but n=68. |
| Starter SO | MAE | 2.27 | Weak (good models ≈ 1.6–1.9). |
| Starter outs | MAE | 5.65 (~1.9 IP) | Weak, driven by workload bias below. |
| Starter pitch count | **bias** | **+8.2 pitches** | Systematic over-projection every single day (+4.7 to +11.0). Inflates outs/SO/hook timing, leaks into totals. |
| Hitter hits 1+ (top-24/day) | avg p vs empirical | 0.651 vs 0.571 | **+8pt over-projection, consistent all 5 days.** |
| Hitter hits 2+ | avg p vs empirical | 0.259 vs 0.207 | +5pt over-projection. |
| Hitter HR (top-18/day) | avg p vs empirical | 0.079 vs 0.130 | **Under-projected ~40%** on its own top HR picks (n≈1,224; ≈5σ). |
| H+R+RBI 2+/3+ | avg p = 0.0, emp = 0.0 | — | **Broken**: both model prob and settled actual are hard-zero. Bug, not signal. |
| Pitcher props at market lines | n = 0 | — | Market lines never reach the eval (`lines_meta.source: null`). |

Live-side evidence: the fitted live ranking model's side priors record **overs hitting 36.7%** (381/1,041) vs unders 50.9% — live over-candidates are systematically bad, and the model is leaning on priors/floors to compensate.

### Backfilled 44-day scorecard (added 2026-07-16)

After backfilling feed_live actuals (618 games fetched) and reconciling all 46 archived sim days, the measured baseline is now **44 days / 547 games / 1,025 starters / 9,846 hitter-prop observations** (May 28–Jul 12, *pre-dating the extras/walk-off engine fixes*):

| Market | Result | Read |
|---|---|---|
| Moneyline | acc 0.554 ±0.042, Brier 0.2472, logloss 0.6876 | Better than the June-week sample suggested; modestly better than coin, still shy of the ~0.57 favorite baseline. The extras top-half bug (fixed) was depressing this. |
| Totals | MAE 3.59 | Confirmed high. |
| Run line (fav −1.5) | acc 0.578, Brier 0.2419 | Held up at scale. |
| Starters | SO MAE 2.06, outs MAE 5.51, **pitch bias +7.35** | Workload over-projection confirmed on n=1,025. Top re-fit target. |
| Hits 1+ | p 0.652 vs emp 0.550 (**+10.2pt**) | Over-projection confirmed at scale; hits 2+ +6.2pt. |
| TB 4+/5+ | p 0.116/0.057 vs emp 0.146/0.067 | **Under**-projected power tail. |
| HR (top-N) | p 0.077 vs emp 0.120 | HR under-projection confirmed (n=9,846). |
| Runs / RBI / 2B / 3B / SB | all within ~2pt | Well calibrated. |

**The single clearest engine-shape diagnosis:** the sim distributes too much of its offense as singles and not enough as extra-base/HR outcomes — hits over-projected ~10pt while TB4+/HR under-projected — with starter workload over-projected ~7 pitches. Phase 1 sweeps should target in-play hit rate down + HR-on-contact/xb-share up simultaneously (they trade off through the same run environment), then re-fit the manager hooks. H+R+RBI buckets now settle correctly (emp 0.421/0.277/0.170/0.095) but model p is 0.0 in all archived artifacts — sims generated after commit `a5cdfb33` will populate real probabilities.

---

## 3. Optimization plan

### Phase 0 — Restore the measurement layer (do first; everything else is blind without it)

1. **Fix odds ingestion on Render** (`refresh_odds_sources.py` failure, stale board date — already on the backlog). Odds are the choke point: no market lines → no locked-card selections → no settlement → empty season eval → `pitcher_props_at_market_lines` n=0.
   *Status 2026-07-16:* could not reproduce locally (full MLB live refresh exits 0; API key shared with Render and healthy, 185K credits). Root-caused the *observability* blackout instead: the job wrapper is DEVNULL'd, `refresh_odds_sources` wiped step stderr before emitting JSON, and the wrapper discarded the parsed result on failure. Fixed in commit `d91b06a7` — failed steps now keep a bounded stderr tail, and a per-sport `failureSummary` is persisted through the Redis-backed refresh-state store (visible via `/api/ops/odds-refresh/status`). **The next failing Render cycle self-reports its traceback; pull it and fix the actual fault.**
2. **Backfill season eval**: raw `feed_live` archives and daily sim artifacts exist for far more days than the 6 evaluated. Run `tools/eval/run_batch_eval_days.py` / `run_season_eval.py` across the season to get 500–1,000+ games of truth data before touching model parameters.
   *Status 2026-07-16:* 46 days of sim artifacts found (May 28–Jul 12); feed_live actuals backfilled via `tools/datasets/backfill_statsapi_feed_live.py` and reconciled per day into the season batch dir.
3. **Fix the H+R+RBI settlement/probability bug** (both sides hard-zero) and switch live registry settlement from normalized-name matching to **MLBAM player IDs** (feed_live carries them; name matching silently drops accents/suffix mismatches).
   *Status 2026-07-16:* root-caused and fixed in commit `a5cdfb33` — the parallel sim chunk (`_simw_chunk`, always used in production) never computed H+R+RBI (missing composite stat + missing `_inc_ge_thresholds` call), and the reconciler looked up the literal `"H+R+RBI"` key in boxscores. ID-based live registry settlement still open.
4. **Stand up a nightly scorecard artifact**: per-market calibration curves (predicted vs empirical by probability bucket), Brier/logloss vs no-vig close, totals distribution PIT/coverage, starter workload bias, prop avg_p vs emp — with alert thresholds. The pieces all exist; they need to run on schedule and publish one canonical JSON+MD.
5. **Track CLV** (line at pick time vs close) for every selection. CLV converges hundreds of bets sooner than ROI and is the primary KPI for whether edges are real.

### Phase 1 — Pregame calibration (ordered by measured deficit × market impact)

1. **Starter workload (+8.2 pitch bias).** Re-fit the manager model with the existing sweeps (`sweep_mgr_starter_hook_add_pitches.py`, `_leash_pc_buffer`, `_third_time_scale`, hard-cap buffers) against the backfilled season. Targets: pitch bias within ±2, outs MAE < 5.0, SO MAE < 2.0. This is the highest-leverage single fix: it directly moves pitcher props and indirectly totals/F5 (bullpen exposure).
2. **Hitter hits over-projection (+5–8pts).** Fit per-prop affine-logit calibration (`tools/tune/fit_hitter_prob_calibration.py`; runtime support already in `prob_calibration.py`) for `hits_1plus`/`hits_2plus`; alternatively find the root cause in in-play hit rate (`sweep_pm_inplay_hit_rate_mult.py`). Prefer root cause + light calibration over heavy calibration alone.
3. **HR under-projection (−40% on top picks).** Sweep `pm_hr_rate_mult` / `hr_on_ball_in_play_factor` and re-validate park/weather HR weights; re-test `FORWARD_BVP_MATCHUP_MODE` on the backfilled holdout (it's off pending "net value on a cleaner holdout" — you'll now have one). HR unders are currently capped to 0 picks in policy, so this is also blocking a whole submarket.
4. **Moneyline (Brier 0.253).** Add a **market-anchored blend**: p_final = σ(w·logit(p_sim) + (1−w)·logit(p_novig_close)), fit w on the backfill (expect w ≈ 0.2–0.4). Sim-only rarely beats the ML market; the sim's job is to disagree *selectively*. Keep pure-sim prob logged alongside for attribution.
5. **Totals & run lines from the same distribution.** Evaluate the *distribution*, not just point MAE: PIT histograms / coverage of the simulated total-runs distribution, and exact-total NLL (already computed). Tune `pm_run_env_sigma` and weather/park weights (`sweep_weather_park_weights.py`) for distribution calibration; run lines, alt lines, F3/F5 and live pricing all inherit correctness from this distribution.
6. **Promotion gates.** No market goes live (or gets cap increases) without passing the existing backtest promotion tools on a true holdout with CLV > 0 and calibration within bucket tolerances.

### Phase 2 — Live modeling & game shapes

1. **Cut live MC noise.** 300 sims ⇒ ±2.9pt (1σ) noise on a 50% win prob — bigger than most live edges. Raise to ≥1,500 effective sims via: batching across ticks, common-random-number reuse, or a precomputed base-out-inning transition/leverage table for the cheap part of the tree, reserving full pitch-level sims for the current PA. Quantify a noise budget per surfaced edge (don't surface an edge smaller than 2× MC σ).
2. **Persist game shapes.** At each live-lens tick, append `{gamePk, ts, inning/outs/bases/score, sim win prob, total dist quantiles (p10/p50/p90), F5 remaining dist, market lines if available}` to the existing JSONL log. This builds the shape library that `analyze_live_prop_trajectories.py` / `analyze_live_prop_projection_shapes.py` already want: expected trajectories by state, so you can detect when the *market's* live line diverges from the re-simmed state (the actual live opportunity signal).
3. **Live prop candidate generation.** Overs hit 36.7% — the candidate generator over-produces overs (likely because pregame over-projection of hits, per Phase 1.2, carries into live pace gaps). After Phase 1 fixes, retrain `live_prop_ranking` on the enlarged settled registry, move from the single `default.json` to per-prop configs (runtime already resolves `market:prop` keys), and add an over-side penalty until measured hit rates normalize.
4. **Live winner/total/RL opportunities.** Same blend discipline as pregame: compare re-simmed state probability vs live no-vig market; surface only when |edge| > threshold + MC noise; log every surfaced edge with market snapshot for CLV-style grading (the live game lens backtest comparer already exists).
5. **Latency & state fidelity.** The live state rebuild is already excellent (count, lineup slot, per-pitcher pitch counts, mid-inning entries). Verify tick cadence end-to-end on Render (live lens report max age is 60s) and that `feed_live` archiving never lapses — it is also the settlement source.

### Phase 3 — Cadence & discipline

- Weekly: refresh calibration fits on trailing 30–45 days (forward-tuning override mechanism already supports dated artifacts); publish scorecard deltas.
- Per change: one parameter family at a time, always sim-vs-actual on a holdout the sweep never saw; keep the `retuned` vs baseline profile A/B structure that already exists.
- Success criteria to declare the engine "market-grade": ML Brier < 0.245 and logloss < 0.685 vs close on 500+ games with positive CLV; totals MAE < 3.2 with calibrated coverage (80% interval covering 78–82%); SO MAE < 1.9, outs MAE < 5.0, pitch bias |≤2|; top-N prop buckets within ±2pts of empirical; live overs/unders hit rates both within noise of breakeven at taken odds.

---

## 4. Engine feature additions (beyond re-fits)

Verified against the engine before recommending: umpire called-strike multipliers, weather (temp/wind/dome with sensitivity knobs), park factors, platoon + statcast shape multipliers, TTO/fatigue, and a reliever `availability_mult` all already exist. What follows is genuinely missing.

**Tier 1 — correctness gaps (✅ ALL THREE FIXED 2026-07-16, `sim_engine/simulate.py` + `models.py`, tests in `tests/test_mlb_sim_extras_rules.py`):**

1. **Extra-innings placed runner (Manfred rule) was not modeled.** Every half-inning started bases-empty, including extras. Fixed: extra half-innings now place the previous lineup spot on 2B (`extras_placed_runner` flag, default on; reach source `"placed"`). Measured: runs per extra half-inning 0.478 → 0.872 (real MLB ≈ 1.0–1.1).
2. **No walk-off termination.** Bottom halves always played to 3 outs even after the home team took the lead in the 9th/extras, inflating totals and home margins in walk-off games. Fixed: game ends at PA granularity once the home team leads in the bottom of the 9th or later (`end_on_walkoff` flag, default on).
3. **Extras ended after the TOP half when the away team led — home team never batted.** The redundant post-half check `state.inning > innings_target and home != away` fired after top halves of inning 10+ (inning increments only after bottom halves), handing the away team every extra-inning game they led at the half. Measured impact with identical rosters over 8,000 paired sims: **home win % 48.05% → 49.76%** (a ~1.7pt structural anti-home bias, now gone). This directly contaminated pregame ML probabilities and every live win-prob estimate in late tied games — a likely contributor to the measured ML Brier 0.253.

These landed before the manager/run-env re-fits deliberately: sweeps run against the buggy engine would have absorbed these distortions into global multipliers.

**Tier 2 — absent features, high value, data already in-house:**

1. **Team defense quality** — no OAA/DRS/BABIP-suppression anywhere; in-play hit rate is batter/pitcher/park/weather only. Per-fielding-team in-play-hit + XB-share multipliers attack the root cause of the +8pt hits over-projection.
2. **Catcher framing** — stacks on the existing umpire called-strike knob; moves SO props (SO MAE 2.27 is weak).
3. **Bullpen fatigue wiring** — trailing 3-day usage → availability is implemented in `daily_update.py` (weights 1.0/0.6/0.4, back-to-back penalties). Keep; verify it survives on Render where feed_live archives must be present.
4. **Starter recent form / velocity trend** from Statcast as a prior on pitcher day-rates (ingestion exists; see §5 — the feature file is stale).
5. **Blowout substitution behavior** — starters are never lifted for defensive/rest subs; affects hitter-prop PA exposure and live unders.

**Tier 3 — later:** day/night + rest/travel splits, per-team baserunning aggressiveness, live velocity-decay hook detection.

**Not now:** new data vendors or ML replacements of the sim while the measurement layer is dark. Every feature goes through the same promotion gate as re-fits (holdout sim-vs-actual + CLV), one family at a time.

---

## 5. Advanced-data availability audit (is current info rolling into daily sims?)

**Current — fetched fresh from StatsAPI on every daily run:** season hitting/pitching stats, platoon (vL/vR) and home/away splits, 14-game recency gamelogs, pitch arsenal usage, probables + confirmed lineups (MLB + Rotowire fallback), injuries, schedule, and per-game weather/park/umpire officials from the live feed (`fetch_game_context`). Bullpen availability is computed from the last 3 days of archived feed_live pitch counts. **This layer is genuinely daily-current.**

**Stale or dormant — the "advanced" layer is NOT rolling forward:**

| Source | State | Impact |
|---|---|---|
| Statcast player features (`data/statcast/features/player_features_latest.json`) | **Covers season 2025 only** (Mar–Nov 2025), generated 2026-05-12; builder (`tools/datasets/build_statcast_player_feature_set.py`, x64 fetch helper) is not on any schedule | Pitch-mix/whiff/in-play/batted-ball-shape multipliers reflect last season; 2026 pitch changes, velo shifts, and rookies invisible |
| Umpire called-strike factor map (`data/umpire/umpire_factors.json`) | **File absent**; `--umpire-x64-prefetch` defaults `off`, needs `.venv_x64` helper | Umpire feature runs effectively neutral in production despite full runtime support |
| BvP HR matchup | `FORWARD_BVP_MATCHUP_MODE = "off"` | Intentional pending holdout proof — fine, revisit after backfill |
| Market odds (game lines + props) | **Broken on Render** (`refresh_odds_sources.py`) | No selections → no settlement → accuracy pipeline dark (Phase 0 item #1) |
| Local artifact mirror | Snapshots end 2026-07-13; eval batches 6 days | Local analysis lags production; Render→repo sync incomplete |

**Verdict:** No — we do *not* have all advanced data current. Core StatsAPI inputs roll daily, but the Statcast feature layer is frozen at 2025, the umpire factor map was never built in production, and odds ingestion is down. Remediation order: (1) fix odds refresh (already Phase 0), (2) schedule the Statcast feature-set build weekly (season-to-date 2026, blended with 2025 by sample size) into the daily/weekly workflow, (3) enable `--umpire-x64-prefetch auto` where the x64 env exists (or port the fetch off the x64 dependency), (4) keep BvP off until the backfilled holdout can judge it.

---

## 6. Key file map

| Concern | Files |
|---|---|
| Core sim | `vendor/mlb_bettingv2/sim_engine/simulate.py`, `pitch_model.py`, `models.py`, `pitcher_distributions.py` |
| Calibration runtime | `sim_engine/prob_calibration.py`, `forward_tuning.py` |
| Live | `sim_engine/live_mc.py`, `live_prop_ranking.py`, `syndicate/features/mlb/live_lens.py` |
| Accuracy surfaces | `syndicate/features/mlb/market_accuracy.py`, `live_lens_daily_accuracy.py` |
| Eval/backfill | `vendor/mlb_bettingv2/tools/eval/run_batch_eval_days.py`, `run_season_eval.py`, `reconcile_daily_sim_artifacts.py` |
| Fit/sweep | `vendor/mlb_bettingv2/tools/tune/*` (manager, pitch-model, calibration fitters) |
| Daily job | `scripts/run_mlb_daily_sim_job.py`, `.github/workflows/daily-update.yml` (06:00 UTC) |
