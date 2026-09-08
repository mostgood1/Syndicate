# FINDINGS — Engine Room Audit: every sim engine, both edge detectors, the intelligence engine

**Session** 2026-09-08, read-only, no code changed, no deploy. User asked: "Syndicate is
failing at its mission" — deep dive on every engine (what works / what doesn't / what data
is missing / what would help), the pregame edge method, the live edge method (resim vs game
shape, interval totals), ideas, and whether the intelligence engine is the right engine or
needs a rebuild. Full report: artifact **"Engine Room Audit"**
(https://claude.ai/code/artifact/d27decea-6287-473e-bc0d-4fe82ba1f33b). Builds on
`findings_2026-09-01_sim_engine_edge_analysis.md`; does not repeat it. Sources: ledger
measured sections, origin/main commits 09-01..09-08, and SEVEN read-only code audits
(MLB, football, basketball, NHL+soccer, pregame edge, live pipeline, intelligence engine
with 4 sub-audits). Substrate is tagged per claim; `local` population figures came from a
checkout **475 commits behind origin/main** and are never claims about Render.

## Verdict (one paragraph)

The simulators are not the failure: four of five engines are calibrated, fed, and carry
real outcome information. What fails is around them: (1) money is staked on `sim − market`,
the sim's error term (corr(edge,win) = −0.14 MLB; `staked_probability` logit blend exists
with ZERO callers); (2) the joint/segment structure — the one output a price-taker cannot
copy — is generated nightly and discarded (MLB keeps marginals + Spearman triangle; football
`quarter_log` has no reader); (3) the loop never closed (0.2% settled; every reliability /
ROI / calibration / policy multiplier reads 1.0); (4) the surfaces where a state-aware sim
is structurally advantaged (segments, intervals, live) are OFF by config or withheld by
policy — **zero sports price any segment live and zero can settle a segment bet**. The
intelligence engine is a 34-function rules pipeline with ≈87 hand-set constants and 0
fitted; replace its DECISION CORE, keep its contracts/ledgers/refusals.

## New from-code facts (not previously in the ledger) `[code, agent audits]`

- **NHL main board IS market-anchored pre-simulation, and the reference doc says otherwise.**
  `market_anchoring.py:144-158` rewrites `period_goal_lambdas` toward the devigged ML at
  weight 0.35; `scripts/build_nhl_artifacts.py:71-80` applies it by default; the production
  generator (`refresh_nhl_oddsapi.py:579-580`) uses defaults; no env flag exists. Published
  ML/PL probabilities are 65/35 model/market; `#470`'s ML backtest was likely scored on
  anchored numbers. Totals are preserved (consistent with totals being the one green cell).
  `hockeysim_engine_reference.md §8` / `grade_nhl_predictions_vs_market.py:23` "opt-in, not
  circular" describes `loaders.py:562`'s flag, which the build script bypasses.
- **Two rankers on two artifacts.** `intelligence_state.py:5580` → `rank_candidates` →
  `recommendation_engine.rank_recommendations` annotates the global pool with
  `adjusted_score`; `pipeline/layer2_shortlist.py:1584` orders the persisted board on
  `blended_score` and never imports `recommendation_engine`. No check they agree.
- **Feedback multipliers are inert by RECENCY, not wiring, and ungated.** The ranker loads
  `load_recent_evaluation_records(days=14)` from `evaluation_ledger_chunks`; newest chunk
  is `2026-07-21.jsonl`, so the window is empty → reliability 1.0 / calibration 0.0 / ROI
  0.0 / policy `balanced`. When settlement writes a chunk the multipliers switch on
  silently with NO sample-size gate, while policy promotion demands 50 settled.
- **Kelly credibility reads two ledgers.** Commit path (`portfolio_commit.py:806` →
  `paper_settlement.settled_decisions_by_sport`) sees real counts (mlb 684 decisions
  2026-09-04); board path (`intelligence_state.py:5528-5534`) reads
  `historical_profile.sample_size` from the evaluation ledger = 0 → 0.25 floor. INFERRED
  from the two call sites, not a runtime log.
- **`blended_score` docstring says "half weight"; code is `_SCORE_SIM_WEIGHT=0.125`
  clamped ±1.5** (`opportunity_signals.py:482,487,749-750`). Documentation defect.
- **Power devig exists and has no production caller**; fair is a MEDIAN over up to 44 books
  incl. Pinnacle (one vote); `_SHARP_BOOKS` is used only for coverage reporting; Kelly uses
  the VIGGED implied (`bankroll_manager.py:127`). Steam flag set (`layer2_board.py:2686`)
  and never read. No RLM/velocity/open-to-now features anywhere.
- **`run_intelligence_query` fans out N+1 times per request** when reasoning steps decompose
  (`intelligence_pipeline.py:1038`), each step missing the question-keyed cache and
  re-hydrating 8 sports; retry wrapper makes worst case 2×(N+1).
- **Football runs on FOUR SCALARS + hardcoded 24.0 s/play**; all three production
  entrypoints construct the input WITHOUT `feature_generation_payload` (checklist:
  `UNWIRED PAYLOAD` ×3, `local`). Totals over-dispersion carrier is
  `drive_success_probability` (`drive_priors.py:332-347`) spanning ~0.45 vs real ~0.10; the
  dial `drive_success_sensitivity` (`calibration_profile.py:122-123`) defaults 1.0 and was
  never fit. `quarter_log` per-quarter points (`game_simulator.py:119-129`) have ZERO
  consumers. NFL live resim is off/unregistered/refuses 94% of games by its own band.
- **Segment line capture: zero `SEGMENT_MARKETS` keys in render.yaml.** Captured only by
  MLB (live, 18 first-N-innings keys) and NBA/WNBA (pregame props refresh intersects
  discovered q1-q4/h1/h2). Football gated OFF (env absent); soccer has no per-event
  segment path (bulk 422s); NCAAB no caller; NHL p1-p3 pregame, priced nowhere.
- **NCAAB has no engine in this repo.** `syndicate/features/ncaab/` = 8 files of readers for
  an external app's `predictions_unified_enriched_<date>.csv`; live_lens renders mirrored
  state and projects nothing; absent from `live_lens_loop._LIVE_LENS_SPORTS` and every join;
  no resolver. The remembered "best live game-shape model" is not here.
- **Basketball:** `form_7/form_30/games_last_3d` consumed (`quarters.py:855`) never
  constructed; `rotation_stints_history` absent (lineup pool off); `period_lines_<date>.csv`
  empty; `quarters_blend_weights.json` absent so 0.95/0.70 anchoring defaults are live;
  all four calibration artifacts have NO scheduled producer; the checklist reads WNBA from
  the wrong root (`source_artifacts/` vs render's `wnba_source/data`) and reports L3
  absent when `smart_sim_total_calibration.json` exists there. `n_sims=100` is the
  live-odds-worker block; refresh-worker takes the 500 default. NBA `p_win=implied+ev` and
  arithmetic American averaging are GONE (`refresh_nba_oddsapi_props.py:1241-1249,906-931`);
  `is_home` 0.0 at `basketball_props_features.py:371` still stands.
- **MLB:** weather reaches `WeatherFactors` only from the StatsAPI live feed (160/554 mirror
  sims carried a temperature, `local`); NWS `weather_<date>.json` has no reader; park
  `hr_mult_override` populated 0/160 (`local`); umpire mult 1.0 in all 160; manager =
  `ManagerProfile()` default for all 30 teams; team defense / framing / runner speed NOT
  MODELLED; TTO quality scaling off (0.0). Hitter-prop calibration is affine-logit
  (18 props, refit 09-01) applied to `p_*_cal`; **ladders `_dist_ladder` price the RAW
  histogram**. Live MC (`live_mc.py`) outputs h2h/margin/total dists and remaining player
  stats — NO segment. `--simulate-rebuild` on archived local rosters: 3 pitcher fails
  (`conditional_arsenal`, `conditional_arsenal_source`, `count_bucket_map`), `local`.
- **Soccer:** anchoring OFF (0.0) → non-circular; market prior backtested null n=600;
  live spreads 874 rows / 0 priceable (market side never written); no `progress_fraction`
  on any soccer live row; corners mean-only and ungradeable (22% of soccer board); cards
  not modelled; results end 05-24 vs odds start 07-31 → zero overlap.
- **Live pipeline:** every join refuses non-`full` segments (`live_gameline_join.py:1029`);
  all five resolvers `segment_refusal`; `game_shape.py` (phase × margin buckets, fitted MLB
  leverage) has NO producer for MLB/basketball; `basketball_interval_projection` is
  research-only and lost to a league constant; `min_edge_pp` floor defaults 0.0 = OFF.

## Recommendations (priority order; detail in the artifact §04-§08)

1. Restore measurement: settlement on; segment actuals in all resolvers; segment line
   capture everywhere; MLB prop freeze/caps; deploy home field with the rate refit.
2. Pricing plane v1: sharp-anchored fair (Pinnacle/exchange, power devig); fitted
   per-(sport, market, segment) logit blend through `staked_probability`; Kelly on the
   blended DE-VIGGED probability; interval-swamps-edge abstention pregame; move the
   basketball anchor OUT of the sim into this layer; make NHL anchoring explicit post-sim.
3. Segments and the joint: persist per-sim vectors; MLB first1/3/5 + rest-of-game from the
   live MC; football drive conversion fitted then 1H distributions + NCAAF live dists;
   NHL periods; first SGP/ladder fair-value vs Kalshi rungs (paper).
4. Game-shape layer, NCAAB first: fitted remaining-total/margin = f(time, score, pace,
   possession/leverage, lineup/foul state) on replayable tapes; quote-age ≤120s; blend
   with resim + live line. Resim is right for state-conditioned full-game; game shape is
   right for interval totals.
5. Intelligence engine: REPLACE the decision core with one seven-stage opportunity
   pipeline (quote plane → model plane → blend → calibrate → abstain+size → route →
   settle/grade/refit); KEEP artifacts, book grid, tick tape, opening ledger, CLV join,
   refusal vocabulary, execution ledger, board contract.
6. Venue-hold routing stays the largest measured lever (+8.48pp gross MLB prop unders).

## What NOT to do (all paid for) — unchanged from 09-01, plus

Do not read NHL's ML backtest as un-anchored; do not cite the "half weight" docstring; do
not let the 14-day multipliers switch on without a sample-size gate.
