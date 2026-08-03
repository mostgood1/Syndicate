# Syndicate End-to-End Assessment — 2026-08-02

> Commissioned as a full maturity audit across every sport ahead of the August transition
> (MLB/WNBA/MLS in-season; NFL/NCAAF/international soccer starting late August).
> Product goal: marry the most accurate game + player-prop sim data with betting-odds edges,
> surface the best opportunities to the Layer 2 board, with world-class pregame AND live boards.
> Seven parallel deep audits: MLB, WNBA, Soccer, NFL+NCAAF, NBA/NHL/NCAAB, Layer 2 engine, Frontend/UX.
> All findings are static-code + artifact audits with file references; live-behavior claims labeled as inference where applicable.

---

## 1. The headline

Syndicate's **forward pipeline** (data → sim → artifacts → board) is genuinely strong — MLB's
pitch-level Monte Carlo, the per-game fingerprint resim triggers, the six self-heal launch reasons,
soccer's calibrated 10-league engine, WNBA's ONNX+SmartSim prop stack, NHL's hockeysim. The
**backward pipeline** (settle → measure → learn → re-rank) is built but not running, and the
**ranking layer** the board actually uses is far simpler than the one that exists in the codebase.

Five cross-cutting findings dominate everything sport-specific:

### F1. The feedback loop is open — nothing ever learns (highest leverage in the repo)
- `EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN` appears **nowhere in render.yaml**
  (`scripts/run_refresh_worker.py:631` gates on it). `reports/performance_summary.json`:
  `settled_count: 0`, `total_bets: 0`, `win_rate: null`, generated 2026-06-10.
- Consequence chain: `settle_result()` has no production caller → every ledger record stays
  `pending` forever → `build_reliability_profile()` returns multiplier 1.0 / calibration_error 0.0
  for every sport/market → **every dynamic threshold in `filter_candidates` is inert** →
  `compare_policies` returns all zeros → policy promotion/A-B never fires.
- `evaluation_settlement.py:33` supports only `("mlb","wnba")` even once enabled.
- The evaluation ledger is also structurally unusable: 4.9GB in
  `reports/intelligence/evaluation_ledger_chunks/` (one 2.8GB chunk) because each record embeds the
  full manifest blob (`intelligence_evaluation.py:452`); `_load_chunked_ledger_records` reads every
  chunk fully into memory. Latest chunk 2026-07-21 — no writes in 12 days.

### F2. The board's real ranker is dead code
- `rank_candidates` → `rank_recommendations` (reliability multipliers, calibration penalty, ROI
  weighting, movement/CLV signals, policy weights) has **zero production callers** — tests only.
- What actually ranks the served board: `score = edge × confidence − tier_penalty`
  (`syndicate/features/intelligence.py:8959`), then `_balanced_recommendation_order` round-robin.
  No EV, no Kelly, no variance, no CLV in the ranking key.
- Unpriced candidates reach the board: `_classify_candidate_with_reason` accepts
  `has_projection OR has_odds` — confirmed 12/12 NFL prop cards in
  `board_snapshot_2026_08_02.json` with blank odds/edge/EV.
- Two different sorts ship in the same JSON: `recommendations` vs `board_contract.cards`
  (`intelligence_board.py:428` re-sorts with no round-robin).
- The Kelly + correlation-aware portfolio engine (`bankroll_manager.py`) exists and works, but the
  published board hardcodes `"portfolio": {}` (`intelligence_state.py:3506`). Bankroll is never
  persisted; `avg_clv` is always None.

### F3. "Live" is only real for MLB (and half-real for soccer)
- MLB: true state-reconstructing 120-sim live Monte Carlo per game per tick. The only one.
- Soccer: real 60s live resim (goal-in-next-N-min, live shots ladders) but live prop candidates
  carry `odds: "-"` (unbettable) and there is **no live odds capture for soccer at all** — all
  soccer odds steps are `phases=("pregame",)`.
- WNBA/NBA: live props are pace extrapolation + calibration ratio — a point estimate with **no
  distribution**, so no true P(over)/live EV. WNBA's live win-prob logistic constants are
  self-documented as never backtested (`wnba/cards.py:872`).
- NHL: live props are **pregame data cosmetically relabeled "live"** — a documented known bug
  (`home.py:4966-4990`).
- NFL/NCAAF/NCAAB/soccer providers: `live_props()` returns `[]`. Football "live lens" is a pregame
  cards re-skin — no live state, no live sim; the team-level smartsim2 engine cannot be seeded
  mid-game (`SmartSim2SimulationInput` always starts Q1).
- The candidate-pool cache (`intelligence_state.py:2496`) is keyed `(date, fingerprint)` with **no
  TTL**, and `/intelligence` has **no client polling** in the template path the engine audit
  checked — freshness chip measures snapshot compute time, not data age.

### F4. Candidate collection is single-point-of-failure for 6 of 8 sports
- Only MLB (five independent builders) and soccer have artifact-direct candidate paths into the
  Layer 2 board. WNBA/NBA/NHL/NCAAB/NFL/NCAAF depend entirely on `home_rails` items.
- This is not theoretical: the 2026-08-02 WNBA props-zeroing (a `limit=12` cap upstream of the
  prop filter), the Alyssa Thomas duplicate, and the id-collision bug were all consequences of
  this one-path design. Three sessions have now patched symptoms of it.
- NFL/NCAAF picks very likely reach the board **mislabeled as player props**: no `market` key is
  set on their pick cards, and `_is_game_level_rank_card_market` returns False for missing market
  (`home.py:4143`) — the exact bug class fixed for WNBA on 2026-07-27. The "12 NFL cards" on the
  live-board audit matches `_standalone_smartsim2_pick_cards`'s `[:12]` cap.

### F5. The docs actively mislead
- NBA's source-app fallback **no longer exists** (deleted in `35e0b4d5`; zero `SOURCE_APP` hits in
  `syndicate/`) — `end_to_end_context.md:387,399`, `nba_wnba_source_fallback_runbook.md`, and three
  dead `render.yaml` env blocks still describe it. The "uncommitted NBA keyvalue fix" in todo.md's
  header shipped as `19e59beb`.
- WNBA's `SYNDICATE_WNBA_SOURCE_APP_BASE_URL/_TOKEN` exist nowhere in code — the only residual
  coupling is the in-repo vendored app loaded in-process (no network). WNBA is ~90% local.
- The live-lens loop covers **four** sports (`_LIVE_LENS_SPORTS = ("mlb","nba","wnba","soccer")`),
  not three. Soccer picks ship despite `syndicate/app.py:260` claiming they don't.

---

## 2. Maturity matrix (1–10, per-audit scores; directional, not perfectly cross-calibrated)

| Sport | Pregame games | Pregame props | Live game | Live props | Evaluation | Frontend |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| **MLB** (in-season) | 8 | 8 | 7 | 6 | 4* | 8 |
| **WNBA** (in-season) | **3.5** | 7 | 5 | 4.5 | 6.5 | 6 |
| **Soccer/MLS** (in-season) | 7.5 | 5.5 | 6 | 4 | **1.5** | 7 |
| **NFL** (starts ~Sep 10) | 6 | 3 | **1** | 0 | 3 | 6 |
| **NCAAF** (starts ~Aug 29) | 6 | **0** | **1** | 0 | 6 | 5 |
| NBA (off-season) | 9 | 8 | 8 | 8 | 7 | 9 |
| NHL (off-season) | 8 | 7 | 6 | **2** | 7 | 6 |
| NCAAB (off-season) | 5 | **1** | 4 | 0 | 2 | 3 |

\* MLB evaluation machinery is the most complete in the repo and also inert (settlement autorun off).

**Engine layer:** candidate coverage 4/10 · ranking quality 3/10 · live lifecycle 5/10 ·
feedback loop 2/10 · portfolio/companion 3/10.
**UX layer:** design consistency 4/10 · info clarity 6.5/10 · live UX 6/10 · **mobile 3.5/10** ·
companion features 4.5/10.

---

## 3. Per-sport state (condensed; full details in the seven audit sections below the roadmap)

### MLB — the reference, deservedly
Real pitch-level MC (rosters, bullpen, stamina, TTO, Statcast shaping); 4 segments (full/F1/F3/F5)
fetched AND simulated; 12 prop markets; five derived prop products; per-game fingerprint scoped
resims; six self-heal triggers; the only true live MC. Remaining gaps: **F1/F3/F5 + runline are
simulated and quoted but never become opportunities** (`_MLB_MARKET_BOARD_DISPLAY_LABELS` has only
ML/total); residual live-prop blanks ~45%/79% (name-matching: loose substring at
`intelligence.py:6033`, no NFKD normalization); Statcast is prose-only at the Layer 2 boundary
(never adjusts scores); hitter-inactive exclusion is dead code (only pulled starters covered);
`estimate_live` failures swallowed by a bare vendor except.

### WNBA — strong props, hollow game markets
Props: genuinely good (ONNX + possession-level SmartSim + two-stage calibration + movement
tracking) — but production runs at **n_sims=100** (default 2000) on the 2GB live-odds-worker, and
refresh-worker has no override (non-deterministic fidelity across services). Game markets: the
critical finding — `p_home_win` falls back to **the book's own implied probability**
(`cards.py:1531-1541`; the sim-margin branch is effectively dead), spread/total probs come from
fixed-scale logistics on point estimates, `*_ev` fields hardcoded None, game recommendations
hardcode `price=-110` and `ev=|edge|/100`. Spread/total book prices are never persisted so the
market board drops those families entirely. Live: logistic blend, no MC, unvalidated constants.
Evaluation: best non-MLB sport (one of two in evaluation_settlement, 5 accuracy pages, a real
live-calibration loop via tuning CSVs).

### Soccer — good engine, no memory, one-league blinders
Calibrated possession→event MC for all 10 leagues (MLS truth score 0.964 vs ASA); real live loop
with goal-in-window and live shots ladders; 2026-27 European schedules already fetched. Gaps:
**zero settlement** (no build_soccer_actuals.py, no reconciliation dir — predictions can never be
scored, calibration block all-None); totals graded only at exactly 2.5 despite a full scoreline
matrix (line ladder is a pure derivation); only 1 of 8 captured prop markets graded; market
anchoring validated (NHL ported it!) but not wired into soccer's own build; no live odds; no picks
route; `_SoccerDataProvider` resolves **one league per call** (`home.py:5087`) — a real bug when
5 European leagues kick off the same Saturday.

### NFL/NCAAF — good bones, three P0 wiring bugs, no live story
Real drive/play MC, full 2026 schedules + projections (NFL 18 wks, NCAAF 1-13,15), 272 NFL games
priced. P0s: **(1) the week never advances** — `_infer_nfl_context`/`_resolve_context` read
`current_week.json` and write the same value back; `nfl_target_week()` solves it correctly and is
never called; Layer 2 NFL context prefers tracked week (`home.py:5842`) → board frozen on Week 1
all season. **(2) NCAAF week pinned to 1** via empty `recommendations_summary/` fallback
(`ncaaf/sources.py:165`). **(3) NFL spread/total odds rows carry no price** (`nfl/cards.py:607,617`)
— prices already on disk unread — so no EV on the two biggest markets; only one side emitted per
market. Also: divisional rematches share one line (96/272 games affected by keying without week);
props plumbing exists (NFL) but data is stubs (one real file: 2025 Super Bowl); receiving-yards
market fetched and silently discarded; smartsim2 is team-level — player attribution in
`contracts.py` is the load-bearing change for real football props. NCAAF has the *better* ongoing
evaluation (performance tracking + betting grading); NFL has only a one-off backtest.
`football/evaluation.py` is dead code with placeholder zero-MAE metrics.

### NBA — best non-MLB module, now fully local
Docs wrong: source-app fallback deleted; serving path survives upstream disappearance (producer
script still shells into `vendor/nba_betting_repo` for some artifacts; `_build_local_*`
counterparts half-built). Deepest live lanes (5 APIs), real per-player live prop path. Open: test
order-pollution (`_NBA_CARDS_CONTEXT_CACHE`, no conftest reset), keyvalue fix never validated live.

### NHL — undersold by the docs, one active mislabeling bug
Full hockeysim MC engine (33 modules, calibration suite, 13 test files); real 1000-sim prop
projections (SOG/G/A/P/BLK/SV) — not lines-only. But live props are pregame data labeled live
(worst correctness bug of the off-season sports), no per-player live lane, no game_detail
(redirect stub `nhl.py:440`), props_lines page is a viewer with no sim/edge join.

### NCAAB — thinnest; Layer 2 is pre-wired for props no pipeline feeds
No props (`SPORT_KEYS` = nba/wnba only), no picks module, live_props hard `[]`, no evaluation
modules, game data flows into the board wearing a prop label. Ironically
`intelligence.py:529-688` already has NCAAB prop correlation priors and parlay pairs waiting.

### Frontend — craft in the board, chaos in the shell
82 templates, only 24 extend base; three forked card clients (~28k near-duplicate lines: NBA
6,562 ≈ WNBA 6,581, MLB a third dialect, NHL a 7,434-line monolith); the Layer 2 board is 1,650
lines of defensive, genuinely smart inline JS; every 60s tick does wholesale innerHTML swaps
(open details close, scroll jumps); default view is an 880px-min 11-column blotter (mobile
hostile); bet slip lands below the whole board on mobile; sport hubs are migration-status pages
written for the developer ("Active migration", literal `\'` bug at `nfl/hub.html:34`); line
movement is one text string despite ~100 lines computing history; zero alerts/watchlist/
personalization/PWA; portfolio page has zero JS; Ask-the-Syndicate is a well-crafted island
(~4,200 backend lines behind a single-shot search box, disconnected from the board).

---

## 4. Roadmap

### Phase 0 — Close the loop + season-critical wiring (days, highest leverage)
1. **Turn on settlement.** Fix the ledger first (store manifest *pointers* not payloads; date-window
   `_load_chunked_ledger_records`; compact/archive the 4.9GB chunks), dry-run the match rate, then
   set `EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN` and extend `_SUPPORTED_SPORTS`.
   Everything else in the "learning" stack (reliability, dynamic thresholds, policy promotion,
   CLV) is downstream of this switch.
2. **Wire `rank_candidates` onto the board path** (replace `_balanced_recommendation_order`'s input
   at `intelligence_state.py:3456`; keep the diversity round-robin on top). ~10 lines to activate
   hundreds of tested lines.
3. **Require a price** to appear in top_opportunities (or an explicit `unpriced` lane).
4. **NFL/NCAAF P0s:** wire `nfl_target_week()` into both resolvers + `home.py:5842`; fix NCAAF
   `default_week()`; pass real spread/total prices (and both sides) into
   `_nfl_market_board_rows_for_game`; add week to the real-lines index key; set `market` on
   football pick cards so game picks stop masquerading as props.
5. **WNBA game markets:** emit sim probabilities + σ into game_cards (or sidecar), delete the
   implied-prob fallback and the `price=-110`/`ev=|edge|/100` fabrications; persist spread/total
   prices through the pipeline.
6. **Soccer multi-league fan-out** in `_SoccerDataProvider` before the Euro season; backfill
   championship/primeira_liga player CSVs; refresh 2026 team histories + rosters; verify OddsAPI
   coverage + call budget for 10 leagues (5M cap).

### Phase 1 — Football season readiness (before Aug 29 / Sep 10)
- NFL evaluation tracking to match NCAAF's; schedule props fetch against real slates; map the
  dropped receiving-yards/interceptions markets; fix the 6-byte stub write; verify the
  weekly-refresh tick-owner race and the autorun process-runaway guard under real load; consider
  tightening the 6h odds cadence for Sunday mornings; NCAAF 2026 rosters re-check.
- Use NCAAF week 1 (Aug 29) as the live dress rehearsal for NFL week 1.

### Phase 2 — World-class engine
- **CLV-first everything:** capture price at recommendation time, stamp true close, make realized
  CLV the primary model-quality metric and the policy-promotion criterion (converges orders of
  magnitude faster than win rate).
- **Kelly staking on every card** (fractional, shrunk by coverage tier + settled sample size);
  surface units, not just edge %. `compute_bet_size` already exists.
- **Portfolio-level correlation exposure budgets** (per game/team/script-cluster stake caps with
  stake shrinkage) replacing the removed greedy filter; surface exposure/diversification.
- **Live distributions for basketball:** carry pregame σ into live hydration, scale by remaining
  minutes → real P(over)/live EV; backtest WNBA live win-prob constants against settled rows
  (the deferred "Phase 5").
- **MLB market expansion:** let F1/F3/F5 + runline become candidates (sim coverage already
  exists); fix the name-normalization gap (NFKD, like `live_lens_daily_accuracy.py:27`).
- **Soccer:** derive the full totals ladder/BTTS/team totals from scoreline_probabilities; grade
  shots/SOT/cards props; wire market anchoring; build build_soccer_actuals.py; add live odds phase.
- **Football player props v1:** player attribution in smartsim2 contracts → pass/rush split →
  usage allocator (mostly built) → per-player distributions from the existing 300-seed run
  (correlation structure for free).
- **Per-sport candidate SLOs:** every sport gets an artifact-direct builder as a second path
  (MLB pattern) + a regression asserting non-zero prop candidates on a synthetic slate + alerting
  on zero-candidate/stale-snapshot/persistence-failure conditions.
- **One ranking, one contract:** board_contract consumes the ranked list; resume the canonical
  board state migration (80% built, stalled on the #39 memory blocker).
- **Freshness:** TTL on the candidate-pool cache for live dates; freshness = oldest underlying
  data timestamp; SSE or polling on the board.

### Phase 3 — World-class companion UX
1. Mobile-first board: cards default on phones, blotter → stacked rows, sticky bottom-sheet bet
   slip with badge.
2. Collapse six filter rails into one control bar with persistence.
3. Stop innerHTML-destroying ticks: keyed row patching + change-flash on edge/odds cells.
4. Line-movement sparklines + opener→now delta pill (data already computed in `renderMovement`).
5. Watchlist + alerts (steam data already flows as `candidate_type === "steam"`).
6. Rewrite the 8 sport hubs as bettor surfaces (slate count, top 3 edges, live-now strip).
7. Portfolio with a live pulse: poll `/api/portfolio/summary`, P/L sparkline, open-bets strip on
   the board rail showing each bet against its live game state.
8. Unify the three forked card clients into `shared/cards_client.js` (until then every UX
   improvement costs 4×).
9. Embed Ask-the-Syndicate in the board: persistent ask bar, "Ask about this pick", today's
   briefing panel, conversation thread.
10. Shell consolidation: migrate standalone templates to base, nav active states, "Sports ▾"
    menu, PWA manifest + theme-color, uniform `?v=asset_version`, retire dead `home.html`
    (keeping home.py's load-bearing candidate builders).

### Hygiene (cheap, do alongside)
- Reconcile stale docs (NBA/WNBA source-app rows, live-lens sport list, soccer status in app.py,
  todo.md's "not committed" header for `19e59beb`); delete dead `render.yaml` env blocks;
  `SYNDICATE_ACTIVE_SPORTS` rollout checklist per season opener; NBA conftest cache-reset fixture;
  delete dead `football/evaluation.py`; NHL game_detail; instrument `estimate_live` failures.

---

*Full per-audit detail retained in session transcript 2026-08-02. Scores are per-audit and
directional. When this doc disagrees with the code, the code wins.*
