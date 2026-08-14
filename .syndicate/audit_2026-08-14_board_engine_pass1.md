# Board / intelligence engine audit — PASS 1: INVENTORY

Mechanical only. No judgement, no code changes. Written 2026-08-14.

**Deployed SHAs at the time of this pass, per the brief's method note:**
`web 5382943c` (20:38:18Z) · `refresh-worker 7b1f3fdc` (20:54:45Z) · `live-odds-worker ccd10349` (19:24:01Z). All three moved during the session; claims below are against the WORKING TREE, which is not any of them.

Scope: `syndicate/features`, `syndicate/blueprints`, `pipeline`, `syndicate/static`, `syndicate/templates`; extensions ['.css', '.html', '.js', '.py']. vendor/, data/, reports/, tests/ excluded.

## 1. Module census — 506 files, 238,071 lines

### Over 1,000 lines (43 files)

| lines | file |
|---:|---|
| 11,068 | `syndicate/features/intelligence.py` |
| 7,467 | `syndicate/blueprints/home.py` |
| 7,434 | `syndicate/templates/nhl/cards_source.html` |
| 6,902 | `pipeline/intelligence_state.py` |
| 6,493 | `syndicate/features/mlb/cards.py` |
| 6,490 | `syndicate/static/wnba/cards-parity.js` |
| 6,471 | `syndicate/static/nba/cards_source.js` |
| 6,369 | `syndicate/features/wnba/cards.py` |
| 5,223 | `syndicate/features/shared/basketball_props_smart_sim.py` |
| 4,967 | `syndicate/features/shared/live_refresh_loop.py` |
| 3,993 | `syndicate/static/nba/cards_source.css` |
| 3,894 | `syndicate/static/wnba/cards-parity.css` |
| 3,881 | `syndicate/static/mlb/cards_source.js` |
| 3,593 | `syndicate/blueprints/ask_the_syndicate_data.py` |
| 3,112 | `syndicate/features/nba/cards.py` |
| 3,049 | `syndicate/blueprints/intelligence.py` |
| 2,945 | `syndicate/blueprints/ops.py` |
| 2,830 | `syndicate/features/shared/odds_refresh_tracking.py` |
| 2,383 | `syndicate/features/shared/intelligence_evaluation.py` |
| 2,301 | `syndicate/static/mlb/cards_exact.css` |
| 2,291 | `syndicate/templates/intelligence.html` |
| 2,262 | `syndicate/features/ncaaf/cards.py` |
| 2,099 | `syndicate/features/ncaaf/cfbd.py` |
| 1,803 | `syndicate/features/shared/artifact_publisher.py` |
| 1,753 | `syndicate/static/shared/board_cards.css` |
| 1,729 | `syndicate/features/shared/recommendation_engine.py` |
| 1,699 | `syndicate/features/shared/layer2_board.py` |
| 1,648 | `syndicate/features/shared/odds_book_quotes.py` |
| 1,645 | `syndicate/features/mlb/live_lens.py` |
| 1,638 | `syndicate/features/shared/memory_observability.py` |
| 1,482 | `syndicate/features/shared/live_lens_local.py` |
| 1,449 | `syndicate/features/nhl/sim_engine/hockeysim/engine.py` |
| 1,440 | `syndicate/features/shared/ops_refresh.py` |
| 1,399 | `syndicate/static/wnba/styles.css` |
| 1,382 | `pipeline/intelligence_pipeline.py` |
| 1,314 | `syndicate/templates/shared/layer1_board.html` |
| 1,176 | `syndicate/static/wnba/betting-card-v2.js` |
| 1,166 | `syndicate/features/shared/refresh_state_store.py` |
| 1,148 | `syndicate/features/mlb/hr_targets.py` |
| 1,130 | `syndicate/features/intelligence_audit.py` |
| 1,052 | `syndicate/features/nhl/cards.py` |
| 1,023 | `syndicate/features/shared/odds_lifecycle.py` |
| 1,010 | `syndicate/static/mlb/cards.css` |

### Top 25 overall

| lines | file |
|---:|---|
| 11,068 | `syndicate/features/intelligence.py` |
| 7,467 | `syndicate/blueprints/home.py` |
| 7,434 | `syndicate/templates/nhl/cards_source.html` |
| 6,902 | `pipeline/intelligence_state.py` |
| 6,493 | `syndicate/features/mlb/cards.py` |
| 6,490 | `syndicate/static/wnba/cards-parity.js` |
| 6,471 | `syndicate/static/nba/cards_source.js` |
| 6,369 | `syndicate/features/wnba/cards.py` |
| 5,223 | `syndicate/features/shared/basketball_props_smart_sim.py` |
| 4,967 | `syndicate/features/shared/live_refresh_loop.py` |
| 3,993 | `syndicate/static/nba/cards_source.css` |
| 3,894 | `syndicate/static/wnba/cards-parity.css` |
| 3,881 | `syndicate/static/mlb/cards_source.js` |
| 3,593 | `syndicate/blueprints/ask_the_syndicate_data.py` |
| 3,112 | `syndicate/features/nba/cards.py` |
| 3,049 | `syndicate/blueprints/intelligence.py` |
| 2,945 | `syndicate/blueprints/ops.py` |
| 2,830 | `syndicate/features/shared/odds_refresh_tracking.py` |
| 2,383 | `syndicate/features/shared/intelligence_evaluation.py` |
| 2,301 | `syndicate/static/mlb/cards_exact.css` |
| 2,291 | `syndicate/templates/intelligence.html` |
| 2,262 | `syndicate/features/ncaaf/cards.py` |
| 2,099 | `syndicate/features/ncaaf/cfbd.py` |
| 1,803 | `syndicate/features/shared/artifact_publisher.py` |
| 1,753 | `syndicate/static/shared/board_cards.css` |

## 2. Duplication census

### 2a. Byte-identical files (1 groups)

- 1 lines, 2 copies:
  - `syndicate/features/football/features/__init__.py`
  - `syndicate/features/football/ingestion/__init__.py`

### 2b. Near-identical, same basename, >=90% (18 pairs)

| similarity | file A | lines | file B | lines |
|---:|---|---:|---|---:|
| 100.0% | `syndicate/templates/nba/market_accuracy.html` | 92 | `syndicate/templates/wnba/market_accuracy.html` | 92 |
| 100.0% | `syndicate/templates/nba/live_prop_audit.html` | 158 | `syndicate/templates/wnba/live_prop_audit.html` | 158 |
| 100.0% | `syndicate/templates/nba/live_prop_accuracy.html` | 151 | `syndicate/templates/wnba/live_prop_accuracy.html` | 151 |
| 100.0% | `syndicate/templates/nba/live_lens_daily_accuracy.html` | 89 | `syndicate/templates/wnba/live_lens_daily_accuracy.html` | 89 |
| 100.0% | `syndicate/templates/nba/live_game_accuracy.html` | 174 | `syndicate/templates/wnba/live_game_accuracy.html` | 174 |
| 99.9% | `syndicate/templates/nba/archive.html` | 269 | `syndicate/templates/wnba/archive.html` | 269 |
| 99.5% | `syndicate/templates/nhl/market_accuracy.html` | 92 | `syndicate/templates/wnba/market_accuracy.html` | 92 |
| 99.1% | `syndicate/templates/nba/reconciliation.html` | 73 | `syndicate/templates/nhl/reconciliation.html` | 74 |
| 99.1% | `syndicate/templates/nba/live_game_accuracy.html` | 174 | `syndicate/templates/nhl/live_game_accuracy.html` | 174 |
| 98.9% | `syndicate/templates/nhl/live_game_accuracy.html` | 174 | `syndicate/templates/wnba/live_game_accuracy.html` | 174 |
| 98.9% | `syndicate/templates/nba/market_accuracy.html` | 92 | `syndicate/templates/nhl/market_accuracy.html` | 92 |
| 98.3% | `syndicate/templates/nhl/live_lens_daily_accuracy.html` | 88 | `syndicate/templates/wnba/live_lens_daily_accuracy.html` | 89 |
| 97.8% | `syndicate/templates/ncaaf/market_board.html` | 64 | `syndicate/templates/nfl/market_board.html` | 65 |
| 94.5% | `syndicate/templates/nba/live_lens_daily_accuracy.html` | 89 | `syndicate/templates/nhl/live_lens_daily_accuracy.html` | 88 |
| 92.0% | `syndicate/templates/mlb/live_lens_daily_accuracy.html` | 80 | `syndicate/templates/nhl/live_lens_daily_accuracy.html` | 88 |
| 91.6% | `syndicate/templates/mlb/live_lens_daily_accuracy.html` | 80 | `syndicate/templates/wnba/live_lens_daily_accuracy.html` | 89 |
| 91.6% | `syndicate/templates/mlb/live_lens_daily_accuracy.html` | 80 | `syndicate/templates/nba/live_lens_daily_accuracy.html` | 89 |
| 90.4% | `syndicate/features/nba/live_game_accuracy.py` | 20 | `syndicate/features/nhl/live_game_accuracy.py` | 20 |

### 2c. Whole file contained inside another (0)

None found by prefix containment.

### 2d. Parallel implementations per concept

**devig / no-vig fair value** — 4 definition(s)

- `syndicate/features/nhl/sim_engine/hockeysim/market_anchoring.py:30  def devig_two_way_home_prob(home_odds: Optional[int], away_odds: Optional[int]) -> Optional[floa`
- `syndicate/features/shared/opportunity_signals.py:112  def devig(prices: Sequence[Any], *, method: str = "multiplicative") -> list[float] | None:`
- `syndicate/features/shared/prop_projections.py:683  def _no_vig_over_probability(row: Mapping[str, Any]) -> float | None:`
- `syndicate/features/soccer/features/market_anchoring.py:31  def devig_decimal_odds(prices: dict[str, float]) -> dict[str, float]:`

**fair probability** — 4 definition(s)

- `syndicate/features/shared/opportunity_signals.py:173  def fair_probability_by_book(`
- `syndicate/features/shared/opportunity_signals.py:203  def consensus_fair_probability(`
- `syndicate/features/shared/recommendation_engine.py:698  def _market_fair_probability(candidate: Mapping[str, Any]) -> tuple[float | None, str | None]:`
- `syndicate/features/shared/recommendation_engine.py:774  def _fair_probability(candidate: Mapping[str, Any]) -> float | None:`

**edge computation** — 4 definition(s)

- `syndicate/features/shared/opportunity_signals.py:548  def model_edge_pct(model_prob: Any, fair_prob: Any) -> float | None:`
- `syndicate/features/shared/quote_enrichment.py:120  def _model_edge_pct(model_prob: Any, fair_prob: Any) -> float | None:`
- `syndicate/features/shared/recommendation_engine.py:779  def calculate_edge(candidate: Mapping[str, Any], *, fair_probability: float | None = None, impli`
- `syndicate/blueprints/ask_the_syndicate_data.py:3273  def _board_min_edge_pct(question: str) -> float | None:`

**candidate ranking** — 5 definition(s)

- `syndicate/features/intelligence.py:10150  def rank_candidates(`
- `syndicate/features/intelligence.py:10605  def _balanced_recommendation_order(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]`
- `syndicate/features/intelligence/api/response_builder.py:288  def _balanced_recommendation_order(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]`
- `syndicate/features/shared/layer2_board.py:1402  def select_shortlist(`
- `syndicate/features/shared/recommendation_engine.py:1503  def rank_recommendations(`

**freshness / staleness** — 19 definition(s)

- `syndicate/features/intelligence.py:6493  def _candidate_live_claim_is_stale(candidate: dict[str, Any]) -> bool:`
- `syndicate/features/mlb/cards.py:2132  def _freshness_display(iso_timestamp: str | None) -> str | None:`
- `syndicate/features/shared/basketball_boxscores_history.py:190  def boxscore_history_is_stale(processed_root: Path, *, max_age_days: int) -> bool:`
- `syndicate/features/shared/basketball_props_smart_sim.py:4018  def _prune_stale_smart_sim_outputs_local(*, processed_root: Path, date_str: str, expected_matchu`
- `syndicate/features/shared/layer1_board.py:180  def _odds_freshness(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:`
- `syndicate/features/shared/live_refresh_loop.py:2374  def _retire_stale_active_pointer(meta: dict[str, Any], *, state: str, detail: str) -> None:`
- `syndicate/features/shared/live_refresh_loop.py:2668  def _mlb_local_sim_run_is_stale() -> bool:`
- `syndicate/features/shared/live_refresh_loop.py:2692  def _kill_stale_mlb_sim_process() -> None:`
- `syndicate/features/shared/odds_lifecycle.py:559  def compact_stale_odds_lifecycle_files(*, root: Path | None = None, today: date | None = None) -`
- `syndicate/features/shared/odds_lifecycle.py:616  def _maybe_compact_stale_odds_lifecycle_files() -> None:`
- `syndicate/features/shared/opportunity_signals.py:404  def _freshness_factor(book_age_seconds: Any, seen_age_seconds: Any = None) -> float:`
- `syndicate/features/shared/recommendation_engine.py:161  def _candidate_freshness_ceiling_seconds(sport_slug: str, *, is_live: bool) -> int:`
- `syndicate/features/shared/simulation_adapter.py:287  def _freshness(context: dict[str, Any], selection: Any, selection_kind: str) -> dict[str, Any]:`
- `syndicate/blueprints/intelligence.py:1838  def _stale_within_threshold(candidate: dict[str, object] | None, *, max_age_days: int = 2) -> bo`
- `syndicate/blueprints/ops.py:374  def _stale_after_days_param() -> int:`
- `pipeline/intelligence_state.py:1036  def _apply_freshness_recompute(container: dict[str, Any]) -> dict[str, Any]:`
- `pipeline/intelligence_state.py:1364  def _freshness_status_from_age(age_seconds: float | None, sla_seconds: int) -> str:`
- `pipeline/intelligence_state.py:1370  def _recomputed_freshness_block(block: dict[str, Any], *, sla_seconds: int | None = None) -> dic`
- `pipeline/intelligence_state.py:6194  def _is_stale(self, snapshot: IntelligenceSnapshot) -> bool:`

**market history / movement** — 23 definition(s)

- `syndicate/features/intelligence.py:9900  def _candidate_movement_magnitude_bonus(candidate: dict[str, Any]) -> float:`
- `syndicate/features/intelligence_board.py:60  def _movement_summary(item: Mapping[str, Any]) -> str:`
- `syndicate/features/live_ui_audit.py:24  def _movement_for_change(previous_edge: float, next_edge: float) -> dict[str, Any]:`
- `syndicate/features/market_data.py:6  def _normalized_movement_history(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:`
- `syndicate/features/market_data.py:69  def _movement_history(candidate: Mapping[str, Any], opening_line: float | None, current_line: fl`
- `syndicate/features/mlb/cards.py:6155  def _mlb_hydrate_market_board_line_movement(row: dict[str, Any], entries: list[dict[str, Any]]) `
- `syndicate/features/mlb/cards.py:6227  def _mlb_hydrate_market_board_prop_movement(row: dict[str, Any], entries: list[dict[str, Any]]) `
- `syndicate/features/nhl/cards.py:734  def _props_movement_from_recommendation(line_value: float | None, price_value: float | None) -> `
- `syndicate/features/nhl/cards.py:759  def _recent_movement_history(row: dict[str, Any], *, line_value: float | None, price_value: floa`
- `syndicate/features/shared/basketball_market_board.py:509  def _basketball_hydrate_market_board_line_movement(row: dict[str, Any], entries: list[dict[str, `
- `syndicate/features/shared/basketball_market_board.py:559  def _basketball_hydrate_market_board_prop_movement(row: dict[str, Any], entries: list[dict[str, `
- `syndicate/features/shared/basketball_props_tracking.py:415  def write_props_movement_signals(`
- `syndicate/features/shared/basketball_props_tracking.py:447  def sync_props_movement_artifacts(`
- `syndicate/features/shared/intelligence_evaluation.py:754  def _movement_context(recommendation: Mapping[str, Any]) -> dict[str, Any]:`
- `syndicate/features/shared/layer2_board.py:1118  def _movement_is_tracked(market: Any) -> bool:`
- `syndicate/features/shared/layer2_board.py:1125  def _movement_shard_keys(commence_time: Any) -> tuple[str, ...]:`
- `syndicate/features/shared/layer2_board.py:1169  def _line_movement_for_row(row: Mapping[str, Any], history: Mapping[str, Any] | None) -> dict[st`
- `syndicate/features/shared/odds_lifecycle.py:781  def build_market_history_view(candidate: Mapping[str, Any] | None = None, *, sport: str | None =`
- `syndicate/features/shared/odds_refresh_tracking.py:682  def _movement_direction(delta: float | None) -> str:`
- `syndicate/features/shared/odds_refresh_tracking.py:1948  def _movement_signal_paths_from_meta(meta: Mapping[str, Any] | None) -> list[Path]:`
- `syndicate/features/shared/recommendation_engine.py:187  def _line_odds_movement_summary(market_features: Mapping[str, Any] | None) -> dict[str, Any] | N`
- `syndicate/features/soccer/market_board.py:476  def _soccer_hydrate_market_board_line_movement(row: dict[str, Any], entry: dict[str, Any] | None`
- `syndicate/blueprints/nhl.py:304  def api_cards_odds_movement():`

**sport routing / inference** — 6 definition(s)

- `syndicate/blueprints/ask_the_syndicate.py:33  _SPORT_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (`
- `syndicate/blueprints/ask_the_syndicate.py:120  def _infer_sport(question: str, context: dict[str, Any]) -> str | None:`
- `syndicate/blueprints/ask_the_syndicate.py:125  for sport, keywords in _SPORT_HINTS:`
- `syndicate/blueprints/ask_the_syndicate.py:136  for sport, keywords in _SPORT_HINTS:`
- `syndicate/blueprints/ask_the_syndicate_data.py:3478  def _fetchers_for_sport(sport: str, question: str) -> list:`
- `syndicate/blueprints/ask_the_syndicate_data.py:3540  # Same reasoning extends to NBA/NHL: _SPORT_HINTS keyword sets don't`

**board contract / card build** — 11 definition(s)

- `syndicate/features/intelligence.py:10658  def _build_board_dictionary(recommendations: list[dict[str, Any]]) -> dict[str, Any]:`
- `syndicate/features/mlb/cards.py:5251  def build_cards_page_context(selected_date: str) -> dict[str, Any]:`
- `syndicate/features/nba/cards.py:2422  def build_cards_page_context(selected_date: str, *, allow_stored_date_fallback: bool = False) ->`
- `syndicate/features/ncaab/cards.py:170  def build_cards_page_context(selected_date: str) -> dict[str, Any]:`
- `syndicate/features/ncaaf/cards.py:2186  def build_cards_page_context(selected_week: int) -> dict[str, Any]:`
- `syndicate/features/nfl/cards.py:468  def build_cards_page_context(selected_week: int, *, season: int | None = None, sort: str = "date`
- `syndicate/features/nhl/cards.py:990  def build_cards_page_context(selected_date: str | None) -> dict[str, Any]:`
- `syndicate/features/shared/game_board_contract.py:580  def apply_game_board_contract(`
- `syndicate/features/shared/layer2_board.py:968  def layer2_rows_to_board_cards(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:`
- `syndicate/features/soccer/cards.py:605  def build_cards_page_context(league: str, week: int | None = None, season: int | None = None) ->`
- `syndicate/features/wnba/cards.py:2950  def build_cards_page_context(`

**prob <-> odds conversion** — 18 definition(s)

- `syndicate/features/bankroll_manager.py:51  def _implied_probability_from_odds(odds: Any) -> float | None:`
- `syndicate/features/intelligence.py:816  def _american_implied_probability(value: float | None) -> float | None:`
- `syndicate/features/intelligence.py:824  def odds_to_implied_probability(value: float | None) -> float | None:`
- `syndicate/features/intelligence.py:828  def _decimal_to_american(value: float | None) -> str | None:`
- `syndicate/features/mlb/cards.py:3004  def _american_implied_prob(value: Any) -> float | None:`
- `syndicate/features/mlb/hr_targets.py:525  def _american_odds_implied_prob(odds: Any) -> float | None:`
- `syndicate/features/nba/cards.py:418  def _implied_prob_from_american(price: float | None) -> float | None:`
- `syndicate/features/ncaab/mirror_export.py:72  def _american_to_probability(price: float | None) -> float | None:`
- `syndicate/features/nhl/sim_engine/hockeysim/features/market_lines.py:32  def _american_to_prob(odds: float) -> Optional[float]:`
- `syndicate/features/nhl/sim_engine/hockeysim/features/market_lines.py:42  def _prob_to_american(prob: float) -> int:`
- `syndicate/features/shared/intelligence_evaluation.py:1362  def _implied_probability_from_american(price: Any) -> float | None:`
- `syndicate/features/shared/odds_book_quotes.py:905  def _implied_probability(price: int) -> float:`
- `syndicate/features/shared/odds_lifecycle.py:771  def _implied_probability_from_american_odds(value: Any) -> float | None:`
- `syndicate/features/shared/odds_refresh_tracking.py:233  def _implied_probability_from_american(value: Any) -> float | None:`
- `syndicate/features/shared/opportunity_signals.py:45  def implied_probability(price: Any) -> float | None:`
- `syndicate/features/shared/quote_enrichment.py:77  def _implied_probability(price: Any) -> float | None:`
- `syndicate/features/shared/recommendation_engine.py:246  def _parse_american_odds(value: Any) -> float | None:`
- `syndicate/features/wnba/cards.py:835  def _implied_prob_from_american(price: float | None) -> float | None:`

## 3. Dead-code candidates (evidence, not verdicts)

### 3a. Routes whose path literal appears nowhere in static/templates/scripts (136 of 348)

Absence here is NOT proof: a caller may build the path dynamically, and chat/ops tooling may call by URL from outside the repo. Treat as a shortlist to verify.

- `/api/accuracy-market`  — defined `syndicate/blueprints/nhl.py:384`
- `/api/accuracy-market`  — defined `syndicate/blueprints/wnba.py:632`
- `/api/betting-card`  — defined `syndicate/blueprints/mlb.py:626`
- `/api/betting-card-api`  — defined `syndicate/blueprints/mlb.py:630`
- `/api/betting-card/`  — defined `syndicate/blueprints/mlb.py:627`
- `/api/betting-recap`  — defined `syndicate/blueprints/nba.py:607`
- `/api/betting-recap`  — defined `syndicate/blueprints/nhl.py:392`
- `/api/cards/bundle`  — defined `syndicate/blueprints/nhl.py:283`
- `/api/cards/dates`  — defined `syndicate/blueprints/nhl.py:270`
- `/api/cards/odds-movement`  — defined `syndicate/blueprints/nhl.py:303`
- `/api/cards/props`  — defined `syndicate/blueprints/nhl.py:437`
- `/api/cards/sim-boxscores`  — defined `syndicate/blueprints/nhl.py:288`
- `/api/cards/sim-detail`  — defined `syndicate/blueprints/nba.py:717`
- `/api/cards/sim-summary`  — defined `syndicate/blueprints/nhl.py:293`
- `/api/dates`  — defined `syndicate/blueprints/nhl.py:259`
- `/api/features`  — defined `syndicate/blueprints/nba.py:668`
- `/api/health`  — defined `syndicate/blueprints/home.py:267`
- `/api/hitter-ladders`  — defined `syndicate/blueprints/mlb.py:557`
- `/api/hitter-top-props`  — defined `syndicate/blueprints/mlb.py:701`
- `/api/home`  — defined `syndicate/blueprints/home.py:7452`
- `/api/hr-targets`  — defined `syndicate/blueprints/mlb.py:435`
- `/api/k-ladder-targets`  — defined `syndicate/blueprints/mlb.py:482`
- `/api/live-game-lens-accuracy`  — defined `syndicate/blueprints/nba.py:589`
- `/api/live-game-lens-accuracy`  — defined `syndicate/blueprints/nhl.py:373`
- `/api/live-game-lens-accuracy`  — defined `syndicate/blueprints/wnba.py:612`
- `/api/live-lens-accuracy`  — defined `syndicate/blueprints/mlb.py:809`
- `/api/live-lens-accuracy`  — defined `syndicate/blueprints/nba.py:580`
- `/api/live-lens-accuracy`  — defined `syndicate/blueprints/nhl.py:365`
- `/api/live-lens-accuracy`  — defined `syndicate/blueprints/wnba.py:622`
- `/api/live-player-props-audit`  — defined `syndicate/blueprints/nba.py:566`
- `/api/live-player-props-audit`  — defined `syndicate/blueprints/wnba.py:580`
- `/api/live-player-props-lens-accuracy`  — defined `syndicate/blueprints/nba.py:571`
- `/api/live-player-props-lens-accuracy`  — defined `syndicate/blueprints/wnba.py:596`
- `/api/live_game_lens_analytics`  — defined `syndicate/blueprints/nhl.py:374`
- `/api/live_game_lens_analytics`  — defined `syndicate/blueprints/wnba.py:613`
- `/api/live_lens_accuracy`  — defined `syndicate/blueprints/wnba.py:623`
- `/api/live_lens_analytics`  — defined `syndicate/blueprints/nhl.py:375`
- `/api/live_lens_analytics`  — defined `syndicate/blueprints/wnba.py:614`
- `/api/live_lens_tuning`  — defined `syndicate/blueprints/nba.py:816`
- `/api/live_lens_tuning`  — defined `syndicate/blueprints/wnba.py:748`
- `/api/live_lines`  — defined `syndicate/blueprints/nba.py:776`
- `/api/live_lines`  — defined `syndicate/blueprints/wnba.py:700`
- `/api/live_pbp_stats`  — defined `syndicate/blueprints/nba.py:797`
- `/api/live_pbp_stats`  — defined `syndicate/blueprints/wnba.py:725`
- `/api/live_player_boxscore`  — defined `syndicate/blueprints/nba.py:738`
- `/api/live_player_boxscore`  — defined `syndicate/blueprints/wnba.py:654`
- `/api/live_player_lens`  — defined `syndicate/blueprints/nba.py:757`
- `/api/live_player_lens`  — defined `syndicate/blueprints/wnba.py:677`
- `/api/live_player_props_lens_analytics`  — defined `syndicate/blueprints/wnba.py:597`
- `/api/live_player_props_projection_audit`  — defined `syndicate/blueprints/wnba.py:581`
- `/api/market-accuracy`  — defined `syndicate/blueprints/mlb.py:823`
- `/api/market-accuracy`  — defined `syndicate/blueprints/nba.py:598`
- `/api/market-accuracy`  — defined `syndicate/blueprints/nhl.py:383`
- `/api/market-accuracy`  — defined `syndicate/blueprints/wnba.py:631`
- `/api/ops/artifacts/publish`  — defined `syndicate/blueprints/ops.py:1118`
- `/api/ops/bootstrap/run`  — defined `syndicate/blueprints/ops.py:953`
- `/api/ops/full-refresh/run`  — defined `syndicate/blueprints/ops.py:2748`
- `/api/ops/intelligence/candidate-trace`  — defined `syndicate/blueprints/ops.py:2336`
- `/api/ops/keyvalue/diagnostics`  — defined `syndicate/blueprints/ops.py:356`
- `/api/ops/keyvalue/expire-run-artifacts`  — defined `syndicate/blueprints/ops.py:703`

### 3b. Env vars read in the board path (127 distinct)

Read sites only. Production values and defaults are Pass 1 follow-up (the brief asks for 73 web vars cross-referenced).

- `ADMIN_TOKEN` — 1 site(s): syndicate/blueprints/ops.py:217
- `ANTHROPIC_API_KEY` — 1 site(s): syndicate/blueprints/ask_the_syndicate_engine.py:150
- `GIT_BRANCH` — 3 site(s): syndicate/blueprints/home.py:173, syndicate/blueprints/home.py:214, syndicate/blueprints/ops.py:187
- `GIT_COMMIT` — 4 site(s): syndicate/features/shared/model_version.py:61, syndicate/blueprints/home.py:167, syndicate/blueprints/home.py:208
- `MALLOC_ARENA_MAX` — 1 site(s): syndicate/features/shared/memory_observability.py:1149
- `MLB_LIVE_LENS_REPORT_MAX_AGE_SECONDS` — 1 site(s): syndicate/features/mlb/live_lens.py:45
- `NBA_BETTING_DATA_ROOT` — 1 site(s): syndicate/blueprints/ask_the_syndicate_data.py:908
- `NHL_DATA_DIR` — 1 site(s): syndicate/blueprints/ask_the_syndicate_data.py:1066
- `ODDS_API_BASE` — 1 site(s): syndicate/blueprints/ops.py:1472
- `ODDS_API_KEY` — 1 site(s): syndicate/blueprints/ops.py:1465
- `QNN_BACKEND_PATH` — 1 site(s): syndicate/features/shared/basketball_props_onnx.py:454
- `QNN_SDK` — 1 site(s): syndicate/features/shared/basketball_props_onnx.py:441
- `QNN_SDK_ROOT` — 1 site(s): syndicate/features/shared/basketball_props_onnx.py:442
- `REDIS_URL` — 2 site(s): syndicate/features/shared/refresh_state_store.py:41, syndicate/features/shared/refresh_state_store.py:83
- `RENDER` — 17 site(s): syndicate/features/mlb/cards.py:176, syndicate/features/nba/cards.py:61, syndicate/features/shared/game_board_contract.py:68
- `RENDER_EXTERNAL_URL` — 6 site(s): syndicate/features/mlb/cards.py:177, syndicate/features/shared/game_board_contract.py:69, syndicate/features/wnba/cards.py:105
- `RENDER_GIT_BRANCH` — 3 site(s): syndicate/blueprints/home.py:172, syndicate/blueprints/home.py:213, syndicate/blueprints/ops.py:186
- `RENDER_GIT_COMMIT` — 6 site(s): syndicate/features/shared/deploy_drain.py:245, syndicate/features/shared/model_version.py:60, syndicate/features/shared/worker_shutdown.py:153
- `RENDER_INSTANCE_ID` — 3 site(s): syndicate/features/shared/ops_refresh.py:447, syndicate/blueprints/home.py:240, syndicate/blueprints/ops.py:206
- `RENDER_SERVICE_ID` — 6 site(s): syndicate/features/mlb/cards.py:178, syndicate/features/shared/artifact_retention.py:120, syndicate/features/shared/game_board_contract.py:70
- `RENDER_SERVICE_NAME` — 5 site(s): syndicate/features/shared/live_refresh_loop.py:2835, syndicate/features/shared/opportunity_contract_metrics.py:143, syndicate/features/shared/ops_refresh.py:436
- `SMARTSIM_WORKERS` — 1 site(s): syndicate/features/shared/basketball_props_smart_sim.py:4860
- `SMART_SIM_WORKERS` — 1 site(s): syndicate/features/shared/basketball_props_smart_sim.py:4860
- `SOURCE_VERSION` — 4 site(s): syndicate/features/shared/model_version.py:62, syndicate/blueprints/home.py:168, syndicate/blueprints/home.py:209
- `SYNDICATE_ACTIVE_SPORTS` — 2 site(s): syndicate/features/shared/live_lens_loop.py:622, syndicate/blueprints/home.py:551
- `SYNDICATE_ADMIN_TOKEN` — 1 site(s): syndicate/blueprints/ops.py:217
- `SYNDICATE_ARTIFACT_EXPORT_MAX_BYTES` — 1 site(s): syndicate/blueprints/ops.py:1407
- `SYNDICATE_ARTIFACT_RETENTION_ENABLED` — 1 site(s): syndicate/features/shared/artifact_retention.py:162
- `SYNDICATE_ASK_CACHE_TTL_SECONDS` — 1 site(s): syndicate/blueprints/ask_the_syndicate.py:335
- `SYNDICATE_ASK_LLM_ENABLED` — 1 site(s): syndicate/blueprints/ask_the_syndicate_engine.py:148
- `SYNDICATE_ASK_LLM_MAX_CALLS` — 1 site(s): syndicate/blueprints/ask_the_syndicate_engine.py:142
- `SYNDICATE_ASK_LLM_WINDOW_SECONDS` — 1 site(s): syndicate/blueprints/ask_the_syndicate_engine.py:143
- `SYNDICATE_ASK_MODEL` — 1 site(s): syndicate/blueprints/ask_the_syndicate_engine.py:288
- `SYNDICATE_BOARD_BUILD_MIN_HEADROOM_MB` — 1 site(s): pipeline/intelligence_state.py:539
- `SYNDICATE_BOARD_TZ` — 1 site(s): syndicate/features/shared/layer1_board.py:73
- `SYNDICATE_DATA_ROOT` — 11 site(s): syndicate/features/football/ingestion/source_fetchers.py:24, syndicate/features/mlb/sources.py:35, syndicate/features/mlb/sources.py:77
- `SYNDICATE_DISK_MAINTENANCE_INTERVAL_SECONDS` — 1 site(s): syndicate/features/shared/disk_maintenance.py:61
- `SYNDICATE_EMPTY_BOARD_PROTECTION_SECONDS` — 1 site(s): pipeline/intelligence_state.py:659
- `SYNDICATE_EVALUATION_LEDGER_MAX_CHUNK_BYTES` — 1 site(s): syndicate/features/shared/intelligence_evaluation.py:608
- `SYNDICATE_EVENT_SIM_FORCE_WINDOW_MINUTES` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:729
- `SYNDICATE_GAME_CANDIDATE_SLOW_LOG_SECONDS` — 1 site(s): syndicate/features/intelligence.py:6421
- `SYNDICATE_GATE_DEMOTE_UNKNOWN_GAME_STATE` — 1 site(s): syndicate/features/shared/opportunity_gate.py:131
- `SYNDICATE_HYDRATED_OVERVIEW_MIN_REBUILD_SEC` — 1 site(s): syndicate/blueprints/home.py:92
- `SYNDICATE_INTELLIGENCE_COMBINED_BOARD_DEFAULT` — 1 site(s): syndicate/blueprints/intelligence.py:208
- `SYNDICATE_INTELLIGENCE_NEWS_TRIGGERED_WINDOW_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:933
- `SYNDICATE_KELLY_FRACTION_MULTIPLIER` — 1 site(s): syndicate/features/bankroll_manager.py:162
- `SYNDICATE_LINEUP_CHECK_INTERVAL_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:561
- `SYNDICATE_LIVE_LENS_INTERVAL_SECONDS` — 1 site(s): syndicate/features/shared/live_lens_loop.py:318
- `SYNDICATE_LIVE_LENS_MIN_HEADROOM_MB` — 1 site(s): syndicate/features/shared/live_lens_loop.py:344
- `SYNDICATE_LIVE_ODDS_PREGAME_RELAUNCH_COOLDOWN_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3346
- `SYNDICATE_LIVE_ODDS_REFRESH_EXECUTION_MODE` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3263
- `SYNDICATE_LIVE_ODDS_REFRESH_IDLE_INTERVAL_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:157
- `SYNDICATE_LIVE_ODDS_REFRESH_INTERVAL_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:148
- `SYNDICATE_LIVE_ODDS_REFRESH_LAUNCH_MODE` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3273
- `SYNDICATE_LIVE_ODDS_REFRESH_MIN_HEADROOM_MB` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3516
- `SYNDICATE_LIVE_ODDS_REFRESH_MODE` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3268
- `SYNDICATE_LIVE_ODDS_REFRESH_PHASE` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3254
- `SYNDICATE_LIVE_ODDS_REFRESH_REGIONS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3259
- `SYNDICATE_LIVE_ODDS_REFRESH_SPORTS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3287
- `SYNDICATE_LIVE_ODDS_REFRESH_STARVATION_CEILING_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3398
- `SYNDICATE_LOOK_AHEAD_INTERVAL_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3101
- `SYNDICATE_MAX_GAME_EXPOSURE_FRACTION` — 1 site(s): syndicate/features/bankroll_manager.py:229
- `SYNDICATE_MLB_EVENING_NEXT_DAY_SIM_START_HOUR` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3028
- `SYNDICATE_MLB_PROPS_REGEN_COOLDOWN_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:1529
- `SYNDICATE_MLB_REFRESH_TICK_OWNER` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:4340
- `SYNDICATE_MLB_SIM_CHECK_INTERVAL_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:971
- `SYNDICATE_MLB_SIM_COUNT` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:989
- `SYNDICATE_MLB_SIM_LOG_DIR` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:2503
- `SYNDICATE_MLB_SIM_MAX_GAMES_PER_RUN` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:1103
- `SYNDICATE_MLB_SIM_MAX_PIPELINE_DEFERS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:1749
- `SYNDICATE_MLB_SIM_MAX_PIPELINE_DEFER_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:1777
- `SYNDICATE_MLB_SIM_MAX_PROGRESS_STALL_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:2608
- `SYNDICATE_MLB_SIM_MIN_MEMORY_HEADROOM_MB` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:1179
- `SYNDICATE_MLB_SIM_TICK_OWNER` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:4320
- `SYNDICATE_MLB_SIM_WORKERS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:998
- `SYNDICATE_MLB_SOURCE_ROOT` — 2 site(s): syndicate/features/mlb/sources.py:31, syndicate/blueprints/ops.py:1836
- `SYNDICATE_MLB_STATCAST_REFRESH_CHECK_INTERVAL_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:2876
- `SYNDICATE_MLB_STATCAST_REFRESH_MAX_AGE_DAYS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:2885
- `SYNDICATE_MLB_WEATHER_INTERVAL_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3743
- `SYNDICATE_NBA_ARTIFACT_ROOT` — 1 site(s): syndicate/features/nba/betting_card.py:73
- `SYNDICATE_NFL_SOURCE_ROOT` — 1 site(s): syndicate/features/nfl/sources.py:79
- `SYNDICATE_ODDS_EVENTS_COMPACT_BYTES` — 1 site(s): syndicate/features/shared/odds_lifecycle.py:464
- `SYNDICATE_ODDS_EVENTS_ROOT` — 1 site(s): syndicate/features/shared/odds_lifecycle.py:212
- `SYNDICATE_ODDS_EVENT_ROOT` — 1 site(s): syndicate/features/shared/odds_lifecycle.py:212
- `SYNDICATE_ODDS_HISTORY_LIMIT` — 1 site(s): syndicate/features/shared/odds_refresh_tracking.py:38
- `SYNDICATE_ODDS_HISTORY_MARKET_STALENESS_CEILING_SECONDS` — 1 site(s): syndicate/features/shared/odds_refresh_tracking.py:78
- `SYNDICATE_ODDS_HISTORY_SHARD_LOOKBACK` — 1 site(s): syndicate/features/shared/odds_lifecycle.py:79
- `SYNDICATE_ODDS_OFF_HOURS_GAME_DAY_MAX_STALENESS_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3703
- `SYNDICATE_ODDS_OFF_HOURS_MAX_STALENESS_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3681
- `SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3983
- `SYNDICATE_REFRESH_LANE` — 3 site(s): syndicate/features/shared/artifact_retention.py:120, syndicate/features/shared/ops_refresh.py:485, syndicate/features/shared/worker_shutdown.py:172
- `SYNDICATE_REFRESH_LAUNCH_MODE` — 2 site(s): syndicate/features/shared/live_refresh_loop.py:3276, syndicate/features/shared/ops_refresh.py:162
- `SYNDICATE_REFRESH_MODE` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3268
- `SYNDICATE_REFRESH_RUN_MAX_RUNTIME_SECONDS` — 1 site(s): syndicate/features/shared/ops_refresh.py:533
- `SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES` — 1 site(s): syndicate/features/shared/ops_refresh.py:460
- `SYNDICATE_REFRESH_STATE_BACKEND` — 2 site(s): syndicate/features/shared/refresh_state_store.py:37, pipeline/intelligence_state.py:176
- `SYNDICATE_REFRESH_STATE_NAMESPACE` — 1 site(s): syndicate/features/shared/refresh_state_store.py:62
- `SYNDICATE_REFRESH_STATE_URL` — 2 site(s): syndicate/features/shared/refresh_state_store.py:41, syndicate/features/shared/refresh_state_store.py:83
- `SYNDICATE_REPORTS_ROOT` — 3 site(s): syndicate/features/shared/refresh_state_store.py:342, syndicate/blueprints/home.py:246, syndicate/blueprints/ops.py:209
- `SYNDICATE_REQUIRE_HOSTED_STORAGE` — 4 site(s): syndicate/features/shared/refresh_state_store.py:46, syndicate/features/shared/request_path_guard.py:26, syndicate/features/shared/source_roots.py:11
- `SYNDICATE_SCHEDULE_ADAPTER_TTL_SECONDS` — 1 site(s): syndicate/features/shared/schedule_adapter.py:74
- `SYNDICATE_SERVICE_ROLE` — 1 site(s): syndicate/features/shared/opportunity_contract_metrics.py:142
- `SYNDICATE_SHADOW_CANDIDATE_LEDGER_ENABLED` — 1 site(s): syndicate/features/shared/shadow_candidate_ledger.py:85
- `SYNDICATE_SHADOW_CANDIDATE_LEDGER_MAX_PER_CYCLE` — 1 site(s): syndicate/features/shared/shadow_candidate_ledger.py:99
- `SYNDICATE_SHADOW_CANDIDATE_LEDGER_RETENTION_DAYS` — 1 site(s): syndicate/features/shared/shadow_candidate_ledger.py:108
- `SYNDICATE_SHADOW_CANDIDATE_LEDGER_SAMPLE_RATE` — 1 site(s): syndicate/features/shared/shadow_candidate_ledger.py:90
- `SYNDICATE_SHORTLIST_EXCLUDED_MARKETS` — 1 site(s): syndicate/features/shared/layer2_board.py:1454
- `SYNDICATE_SHORTLIST_MIN_IMPLIED_BOOK_TOTAL_PCT` — 1 site(s): syndicate/features/shared/layer2_board.py:1241
- `SYNDICATE_SLOW_ENRICH_TOTAL_SECONDS` — 1 site(s): syndicate/features/shared/quote_enrichment.py:407
- `SYNDICATE_SLOW_ROW_TOTAL_SECONDS` — 1 site(s): syndicate/blueprints/home.py:2905
- `SYNDICATE_SOCCER_LIVE_LENS_MIN_HEADROOM_MB` — 1 site(s): syndicate/features/shared/live_lens_loop.py:370
- `SYNDICATE_SOCCER_LIVE_LENS_TICK_SIMULATIONS` — 1 site(s): syndicate/features/shared/live_lens_loop.py:130
- `SYNDICATE_SOCCER_RESIM_CHECK_INTERVAL_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3546
- `SYNDICATE_SOCCER_RESIM_TICK_OWNER` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3539
- `SYNDICATE_STATE_ROOT` — 1 site(s): syndicate/features/shared/refresh_state_store.py:342
- `SYNDICATE_TRACEMALLOC_DIAG` — 1 site(s): syndicate/features/shared/memory_observability.py:1562
- `SYNDICATE_WEB_DYNO` — 4 site(s): syndicate/features/mlb/cards.py:172, syndicate/features/nba/cards.py:58, syndicate/features/shared/game_board_contract.py:64
- `SYNDICATE_WNBA_CARDS_CONTEXT_HARD_MAX_AGE_SECONDS` — 1 site(s): syndicate/features/wnba/cards.py:3131
- `SYNDICATE_WNBA_CARDS_CONTEXT_MAX_AGE_SECONDS` — 1 site(s): syndicate/features/wnba/cards.py:3075
- `SYNDICATE_WNBA_CARDS_CONTEXT_PUBLISH_ENABLED` — 1 site(s): syndicate/features/wnba/cards.py:3091
- `SYNDICATE_WNBA_LIVE_LENS_MIN_HEADROOM_BYTES` — 1 site(s): syndicate/features/shared/live_lens_loop.py:438
- `SYNDICATE_WNBA_ODDS_REFRESH_STARVATION_CEILING_SECONDS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:3485
- `WEB_CONCURRENCY` — 1 site(s): syndicate/features/shared/odds_book_quotes.py:658
- `WEEKLY_SPORTS_GAME_HORIZON_DAYS` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:4356
- `WEEKLY_SPORTS_REFRESH_TICK_OWNER` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:4390
- `WERKZEUG_RUN_MAIN` — 1 site(s): syndicate/features/shared/live_refresh_loop.py:4945
- `WNBA_BETTING_DATA_ROOT` — 1 site(s): syndicate/blueprints/ask_the_syndicate_data.py:480

## 4. CORRECTIONS TO THE BRIEF'S "KNOWN ALREADY" INPUTS

The brief supplies prior findings as inputs "not to be re-derived". Two do not
hold against the working tree, and one method hazard invalidates ad-hoc greps.

- **`syndicate/static/mlb/board.js` DOES NOT EXIST.** `[measured]` The brief
  lists it twice — as a byte-identical duplicate of the first 52 lines of
  `shared/game_board.js`, and as a confirmed dead-code instance.
  `game_board.js` exists; `mlb/board.js` does not. Either a cleanup lane already
  deleted it, or the finding was stale when the brief was written. **Both
  citations should be struck**, and whoever owns the brief should re-check the
  other four dead-code "confirmed" items the same way before they are treated as
  established. This is why the census found 1 exact-duplicate group rather than
  the expected 2.
- **The devig count is not settled at 5.** `[measured]` A name-shaped regex over
  the board path finds **4**; a widened grep for `devig|no_vig|overround|vig_free`
  finds more sites, including `syndicate/features/nhl/sim_engine/hockeysim/
  market_anchoring.py` and `syndicate/features/soccer/features/market_anchoring.py`,
  which are per-sport market-anchoring code the narrow pattern misses entirely.
  **The real number depends on whether sport sim-engine anchoring counts as "a
  devig implementation" — that is a Pass 2 semantic judgement, not a Pass 1
  count.** Recorded as unclear per the scoping rule rather than guessed.
- **METHOD HAZARD, applies to every pass: `.claude/worktrees/` holds FULL REPO
  COPIES.** `[measured]` An unscoped `rglob("*.py")` returned
  `.claude/worktrees/jovial-proskuriakova-69c4b2/...` and
  `.claude/worktrees/laughing-murdock-e728df/...` alongside the real tree —
  every hit duplicated 3x. Any census, hash or grep that does not exclude
  `.claude/`, `vendor/`, `__pycache__/` will triple-count and manufacture
  duplication findings. The Pass 1 numbers above are scoped to explicit
  directories and are NOT affected; ad-hoc verification greps are.

## 5. WHAT PASS 1 DID NOT DO

Stated so the gaps are not mistaken for clean results.

- **§2 config duplication is only half done.** 127 env vars are read in the
  board path; the brief asks for each cross-referenced against the web service's
  73 configured values with defaults and current production values. The read
  sites are listed; the cross-reference is not done. Note the denominators
  differ (read-sites in the board path vs keys configured on one service) and
  should not be compared directly.
- **§2 copy-forked sport modules**: the 18 near-identical pairs are listed, but
  classifying each difference as *legitimate sport semantics* vs *drift* is a
  Pass 2 judgement and was deliberately not attempted.
- **§3 dead code**: only the mechanical sweeps ran (route literals, env reads).
  The "every observed return is None/[]/{}" sweep and the feature-flag-never-on
  sweep need runtime or config evidence and are Pass 2/3.
- **136 routes whose path literal appears nowhere is a SHORTLIST, not a finding.**
  Dynamically-built paths, ops tooling calling by URL from outside the repo, and
  chat surfaces would all produce a false positive. Each needs its own evidence
  before it reaches a deletion list.
