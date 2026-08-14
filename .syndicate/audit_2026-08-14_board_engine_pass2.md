# Board / intelligence engine audit — PASS 2: SEMANTICS (PARTIAL)

Read-only. No code changes. Written 2026-08-14, after Pass 1's note.

**SCOPE OF THIS NOTE, stated first so it is not mistaken for the whole pass.**
Covers **§5 concept ownership** and **§7 the 50/50 pattern**. **§4 pipeline topology and §6 state/artifact topology are NOT DONE** — see the closing section for exactly what they owe and why they were not attempted.

Scope: `syndicate/**` + `pipeline/**`, 390 python files. `.claude/worktrees/`, `vendor/`, `__pycache__` excluded — Pass 1 recorded that those hold full repo copies and triple-count.

## §5. Concept ownership — definition sites per term

A term with many *definition* sites is a term nobody owns. This lists where each is DEFINED or ASSIGNED, not where it is read — reads are cheap, definitions are where meaning is set and where two of them can disagree.

| term | definition sites | verdict |
|---|---:|---|
| `edge` | 231 | **NO OWNER** |
| `value` | 1220 | **NO OWNER** |
| `ev` | 207 | **NO OWNER** |
| `model_edge_pct` | 3 | **contested** |
| `min_value_pct` | 2 | single owner |
| `fair_probability` | 16 | **NO OWNER** |
| `market_probability` | 25 | **NO OWNER** |
| `implied_probability` | 84 | **NO OWNER** |
| `confidence` | 142 | **NO OWNER** |
| `score` | 310 | **NO OWNER** |
| `model_skill` | 0 | single owner |
| `candidate` | 244 | **NO OWNER** |
| `opportunity` | 5 | **contested** |
| `selection` | 190 | **NO OWNER** |
| `pick` | 119 | **NO OWNER** |
| `recommendation` | 120 | **NO OWNER** |
| `shortlist` | 8 | **contested** |
| `board` | 163 | **NO OWNER** |
| `snapshot` | 229 | **NO OWNER** |

### Per-term sites (capped at 12 each)

**`edge`** — 231 site(s)

- `pipeline/intelligence_models.py:185` — `edge=payload.get("edge"),`
- `pipeline/intelligence_pipeline.py:1104` — `"edge": 0`
- `pipeline/intelligence_state.py:1842` — `def _normalize_card_edge_units(card: dict[str, Any]) -> None:`
- `pipeline/intelligence_state.py:1863` — `edge = card.get("edge")`
- `pipeline/intelligence_state.py:1891` — `def intelligence_ledger_recording_enabled() -> bool:`
- `pipeline/intelligence_state.py:1982` — `def _canonical_board_state_ledger_fingerprint_path() -> Path:`
- `pipeline/intelligence_state.py:1994` — `def _record_canonical_board_state_ledger_fingerprint(selected_date: str, fingerprint: str) -> None:`
- `pipeline/intelligence_state.py:2001` — `def maybe_record_board_state_to_evaluation_ledger(state: dict[str, Any]) -> dict[str, Any] | None:`
- `pipeline/intelligence_state.py:3939` — `"edge": candidate.get("edge"),`
- `pipeline/performance_aggregator.py:77` — `def _normalized_prediction_ledger_records(ledger_path: Path | str | None = None) -> list[dict[str, Any]]:`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:284` — `"edge": None,`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:308` — `"edge": _to_float(top.get("adjusted_edge") or top.get("edge") or top.get("price_edge_pct")),`
- ...and 219 more

**`value`** — 1220 site(s)

- `pipeline/evidence_builder.py:25` — `value = payload.get(key)`
- `pipeline/evidence_builder.py:32` — `def _first_value(payload: Mapping[str, Any], keys: Sequence[str]) -> Any:`
- `pipeline/evidence_builder.py:55` — `value=normalized_value,`
- `pipeline/evidence_builder.py:105` — `"value": step.get("result_count") if step.get("result_count") is not None else step.get("score"),`
- `pipeline/intelligence_models.py:81` — `value=payload.get("value") if "value" in payload else payload.get("result") if "result" in payload else payloa`
- `pipeline/intelligence_pipeline.py:274` — `{"label": "generated_at", "value": control_plane.get("generated_at")},`
- `pipeline/intelligence_pipeline.py:275` — `{"label": "date", "value": control_plane.get("date")},`
- `pipeline/intelligence_pipeline.py:276` — `{"label": "phase", "value": control_plane.get("phase")},`
- `pipeline/intelligence_pipeline.py:277` — `{"label": "execution_mode", "value": control_plane.get("execution_mode")},`
- `pipeline/intelligence_pipeline.py:278` — `{"label": "summary_ok", "value": control_plane.get("summary_ok")},`
- `pipeline/intelligence_pipeline.py:348` — `{"label": "multi_sport", "value": bool(context_awareness.get("multi_sport"))},`
- `pipeline/intelligence_pipeline.py:349` — `{"label": "confidence", "value": context_awareness.get("confidence")},`
- ...and 1208 more

**`ev`** — 207 site(s)

- `pipeline/evidence_builder.py:39` — `def _evidence_from_payload(payload: Mapping[str, Any], *, source_type: str | None = None, default_timestamp: s`
- `pipeline/evidence_builder.py:122` — `def build_evidence_records(raw_output: Any, *, selected_date: str | None = None) -> tuple[Evidence, ...]:`
- `pipeline/evidence_builder.py:161` — `def attach_evidence(result: IntelligenceResult, raw_output: Any, *, selected_date: str | None = None) -> Intel`
- `pipeline/intelligence_models.py:326` — `def build_evaluation_record(self, *, outcome: Mapping[str, Any] | None = None) -> dict[str, Any]:`
- `pipeline/intelligence_pipeline.py:98` — `def _log_json_event(event: str, **fields: Any) -> None:`
- `pipeline/intelligence_pipeline.py:262` — `def _odds_control_plane_evidence(context: dict[str, Any]) -> dict[str, Any] | None:`
- `pipeline/intelligence_pipeline.py:312` — `def _comparison_evidence(context: dict[str, Any], recommendations: list[dict[str, Any]], context_awareness: di`
- `pipeline/intelligence_pipeline.py:360` — `def _cross_sport_evidence(context: dict[str, Any], recommendations: list[dict[str, Any]], context_awareness: d`
- `pipeline/intelligence_pipeline.py:408` — `def _recommendation_evidence(context: dict[str, Any], recommendations: list[dict[str, Any]], context_awareness`
- `pipeline/intelligence_pipeline.py:564` — `def _normalize_preview_text(value: Any) -> str:`
- `pipeline/intelligence_pipeline.py:568` — `def _preview_candidate_score(candidate: Mapping[str, Any], preview_subject: str) -> float:`
- `pipeline/intelligence_pipeline.py:608` — `def _preview_related_recommendations(recommendations: list[dict[str, Any]], preview_subject: str, *, candidate`
- ...and 195 more

**`model_edge_pct`** — 3 site(s)

- `syndicate/features/shared/layer2_board.py:1061` — `"model_edge_pct": row.get("model_edge_pct"),`
- `syndicate/features/shared/opportunity_signals.py:548` — `def model_edge_pct(model_prob: Any, fair_prob: Any) -> float | None:`
- `syndicate/features/shared/quote_enrichment.py:120` — `def _model_edge_pct(model_prob: Any, fair_prob: Any) -> float | None:`

**`min_value_pct`** — 2 site(s)

- `syndicate/blueprints/intelligence.py:2755` — `"min_value_pct": shortlist.get("min_value_pct"),`
- `syndicate/features/shared/layer2_board.py:1661` — `"min_value_pct": value_floor,`

**`fair_probability`** — 16 site(s)

- `pipeline/intelligence_state.py:1815` — `fair_probability = _num(quote.get("fair_probability"))`
- `syndicate/features/shared/book_margin_model.py:199` — `"fair_probability": round(fair, 4),`
- `syndicate/features/shared/layer2_board.py:816` — `"fair_probability": fair,`
- `syndicate/features/shared/odds_book_quotes.py:1073` — `return {"fair_probability": None, "fair_price": None, "hold_pct": None, "sides_quoted": 0}`
- `syndicate/features/shared/odds_book_quotes.py:1090` — `return {"fair_probability": None, "fair_price": None, "hold_pct": None, "sides_quoted": 0}`
- `syndicate/features/shared/odds_book_quotes.py:1093` — `"fair_probability": round(fair, 6),`
- `syndicate/features/shared/opportunity_signals.py:173` — `def fair_probability_by_book(`
- `syndicate/features/shared/opportunity_signals.py:203` — `def consensus_fair_probability(`
- `syndicate/features/shared/quote_enrichment.py:521` — `fair_probability = quote.get("fair_probability")`
- `syndicate/features/shared/recommendation_engine.py:698` — `def _market_fair_probability(candidate: Mapping[str, Any]) -> tuple[float | None, str | None]:`
- `syndicate/features/shared/recommendation_engine.py:774` — `def _fair_probability(candidate: Mapping[str, Any]) -> float | None:`
- `syndicate/features/shared/recommendation_engine.py:823` — `"fair_probability": round(float(fair_probability_value), 4) if fair_probability_value is not None else None,`
- ...and 4 more

**`market_probability`** — 25 site(s)

- `syndicate/blueprints/ask_the_syndicate_adapter.py:283` — `"market_probability": None,`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:307` — `"market_probability": _to_pct(top.get("market_probability") or top.get("implied_probability")),`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:377` — `"market_probability": _to_pct(row.get("market_probability") or row.get("implied_probability")),`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:501` — `"market_probability": _to_pct(item.get("market_probability") or item.get("implied_probability")),`
- `syndicate/features/intelligence.py:1859` — `market_probability = _numeric_hint(candidate.get("market_probability") or market_context.get("implied_probabil`
- `syndicate/features/intelligence.py:1912` — `"market_probability": market_probability,`
- `syndicate/features/intelligence_analysis_common.py:56` — `market_probability = _normalize_probability(candidate.get("market_probability") or market_context.get("implied`
- `syndicate/features/intelligence_analysis_common.py:108` — `market_probability = _normalize_probability(candidate.get("market_probability") or market_context.get("implied`
- `syndicate/features/intelligence_analysis_common.py:143` — `"market_probability": market_probability,`
- `syndicate/features/shared/odds_framework.py:64` — `market_probability = _candidate_market_probability(row)`
- `syndicate/features/shared/odds_framework.py:74` — `def _candidate_market_probability(row: Mapping[str, Any]) -> float | None:`
- `syndicate/features/shared/odds_framework.py:103` — `market_probability = _candidate_market_probability(row)`
- ...and 13 more

**`implied_probability`** — 84 site(s)

- `pipeline/intelligence_state.py:3945` — `"implied_probability": candidate.get("implied_probability"),`
- `pipeline/performance_aggregator.py:95` — `"implied_probability": _safe_probability(`
- `syndicate/blueprints/intelligence.py:2093` — `implied_probability=payload.get("implied_probability"),`
- `syndicate/features/bankroll_manager.py:51` — `def _implied_probability_from_odds(odds: Any) -> float | None:`
- `syndicate/features/bankroll_manager.py:124` — `implied_probability = _safe_float(base_candidate.get("implied_probability"))`
- `syndicate/features/bankroll_manager.py:128` — `implied_probability = _implied_probability_from_odds(base_candidate.get("odds"))`
- `syndicate/features/bankroll_manager.py:129` — `implied_probability = _clamp(implied_probability if implied_probability is not None else 0.5, 0.0, 1.0)`
- `syndicate/features/bankroll_manager.py:145` — `"implied_probability": round(implied_probability, 4),`
- `syndicate/features/intelligence.py:816` — `def _american_implied_probability(value: float | None) -> float | None:`
- `syndicate/features/intelligence.py:824` — `def odds_to_implied_probability(value: float | None) -> float | None:`
- `syndicate/features/intelligence.py:1002` — `implied_probability = odds_to_implied_probability(american_odds)`
- `syndicate/features/intelligence.py:1010` — `"implied_probability": round(implied_probability * 100.0, 2) if implied_probability is not None else None,`
- ...and 72 more

**`confidence`** — 142 site(s)

- `pipeline/intelligence_models.py:180` — `confidence=str(payload.get("confidence") or "").strip() or None,`
- `pipeline/intelligence_pipeline.py:548` — `"confidence": item.get("confidence"),`
- `pipeline/intelligence_pipeline.py:900` — `confidence = "low" if vague else "medium" if not has_sport or not has_market else "high"`
- `pipeline/intelligence_pipeline.py:903` — `"confidence": confidence,`
- `pipeline/intelligence_state.py:1828` — `confidence = _num(score.get("book_confidence"))`
- `pipeline/intelligence_state.py:3666` — `confidence = cls._candidate_numeric_value(`
- `pipeline/intelligence_state.py:3943` — `"confidence": candidate.get("confidence"),`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:286` — `"confidence": None,`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:310` — `"confidence": _to_pct(top.get("confidence") or top.get("model_probability")),`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:380` — `"confidence": _to_pct(row.get("confidence") or row.get("model_probability")),`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:504` — `"confidence": _to_pct(item.get("confidence") or item.get("model_probability")),`
- `syndicate/blueprints/ask_the_syndicate_engine.py:64` — `"confidence": {`
- ...and 130 more

**`score`** — 310 site(s)

- `pipeline/intelligence_models.py:186` — `score=_parse_float(payload.get("score")),`
- `pipeline/intelligence_pipeline.py:549` — `"score": item.get("score"),`
- `pipeline/intelligence_pipeline.py:568` — `def _preview_candidate_score(candidate: Mapping[str, Any], preview_subject: str) -> float:`
- `pipeline/intelligence_pipeline.py:569` — `score = (_numeric_hint(candidate.get("score")) or 0.0) / 100.0`
- `pipeline/intelligence_state.py:1726` — `def _score(side: str) -> float | None:`
- `pipeline/intelligence_state.py:1806` — `score = card.get("score_breakdown") if isinstance(card.get("score_breakdown"), Mapping) else {}`
- `pipeline/intelligence_state.py:1808` — `score = card.get("score") if isinstance(card.get("score"), Mapping) else {}`
- `pipeline/intelligence_state.py:3656` — `score = cls._candidate_numeric_value(`
- `pipeline/intelligence_state.py:3934` — `def _candidate_preliminary_scores(self, candidate: dict[str, Any]) -> dict[str, Any]:`
- `pipeline/intelligence_state.py:3936` — `"score": candidate.get("score"),`
- `pipeline/intelligence_state.py:4234` — `def _attach_adjusted_scores(global_pool: list[dict[str, Any]], selected_date: str | None = None) -> None:`
- `syndicate/local_nhl_odds.py:137` — `def _nhl_scoreboard_line(home_goals: object, away_goals: object) -> object:`
- ...and 298 more

**`candidate`** — 244 site(s)

- `pipeline/intelligence_pipeline.py:568` — `def _preview_candidate_score(candidate: Mapping[str, Any], preview_subject: str) -> float:`
- `pipeline/intelligence_state.py:121` — `def _board_window_candidate_dates(today: str | None = None) -> list[str]:`
- `pipeline/intelligence_state.py:199` — `def _candidate_has_price(candidate: Mapping[str, Any]) -> bool:`
- `pipeline/intelligence_state.py:217` — `def _default_unbounded_candidate_cap() -> int:`
- `pipeline/intelligence_state.py:1148` — `def _intelligence_state_candidate_count(state: dict[str, Any] | None) -> int:`
- `pipeline/intelligence_state.py:1513` — `def _intelligence_state_daily_candidates() -> dict[str, list[Path]]:`
- `pipeline/intelligence_state.py:2833` — `candidate = json.loads(path.read_text(encoding="utf-8-sig"))`
- `pipeline/intelligence_state.py:3292` — `def _abort_build_candidate_pool_if_memory_critical(stage: str) -> bool:`
- `pipeline/intelligence_state.py:3605` — `def _merge_candidate_pools(candidate_pools: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:`
- `pipeline/intelligence_state.py:3614` — `def _candidate_numeric_value(candidate: dict[str, Any], *keys: str) -> float | None:`
- `pipeline/intelligence_state.py:3631` — `def _candidate_timestamp_value(candidate: dict[str, Any]) -> float | None:`
- `pipeline/intelligence_state.py:3654` — `def _rank_fallback_candidates(cls, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:`
- ...and 232 more

**`opportunity`** — 5 site(s)

- `syndicate/blueprints/opportunity_board.py:56` — `def opportunity_board():`
- `syndicate/blueprints/opportunity_board.py:72` — `def api_opportunity_board():`
- `syndicate/blueprints/ops.py:311` — `def api_ops_opportunity_contract_status() -> Any:`
- `syndicate/features/intelligence.py:179` — `def _normalize_opportunity_item(item: Any) -> dict[str, Any]:`
- `syndicate/features/intelligence.py:260` — `def _normalize_opportunity_list(key: str) -> None:`

**`selection`** — 190 site(s)

- `pipeline/intelligence_pipeline.py:1103` — `"selection": "FALLBACK: pipeline failed",`
- `pipeline/intelligence_state.py:4142` — `selection = str(candidate_payload.get("selection") or candidate_payload.get("pick") or candidate_payload.get("`
- `syndicate/local_nhl_odds.py:342` — `selection = str(outcome.get("name") or "").strip().lower()`
- `syndicate/local_nhl_odds.py:882` — `"selection": side or None,`
- `syndicate/local_nhl_odds.py:895` — `selection = "over"`
- `syndicate/local_nhl_odds.py:897` — `selection = "under"`
- `syndicate/local_nhl_odds.py:899` — `selection = "home"`
- `syndicate/local_nhl_odds.py:901` — `selection = "away"`
- `syndicate/local_nhl_odds.py:903` — `selection = lowered or None`
- `syndicate/local_nhl_odds.py:914` — `"selection": selection,`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:281` — `"selection": None,`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:302` — `selection = top.get("selection") or top.get("pick") or top.get("name") or top.get("label")`
- ...and 178 more

**`pick`** — 119 site(s)

- `pipeline/intelligence_models.py:173` — `pick=str(payload.get("pick") or "").strip() or None,`
- `syndicate/blueprints/ask_the_syndicate_data.py:933` — `def pick(*keys: str) -> str:`
- `syndicate/blueprints/home.py:872` — `pick = _safe_text(row.get("display_pick") or row.get("selection") or row.get("market_label"), "Market")`
- `syndicate/blueprints/home.py:951` — `pick = str(market.get("pick") or "").strip()`
- `syndicate/blueprints/home.py:1308` — `pick = _safe_text(item.get("pick") or item.get("selection"), "Play")`
- `syndicate/blueprints/home.py:1775` — `pick = str(selection or "").strip().lower()`
- `syndicate/blueprints/home.py:1884` — `def _player_name_from_prop_pick_text(pick_text: str) -> str | None:`
- `syndicate/blueprints/home.py:1916` — `def _market_label_from_pick_text(text: str) -> str:`
- `syndicate/blueprints/home.py:2075` — `def _candidate_pick_text(item: dict[str, Any]) -> str:`
- `syndicate/blueprints/home.py:2154` — `"pick": _candidate_pick_text(item),`
- `syndicate/blueprints/home.py:2477` — `"pick": pick_text,`
- `syndicate/blueprints/home.py:2622` — `pick=_first_present_text(row.get("display_pick"), row.get("selection"), row.get("pick")) or "-",`
- ...and 107 more

**`recommendation`** — 120 site(s)

- `pipeline/intelligence_pipeline.py:408` — `def _recommendation_evidence(context: dict[str, Any], recommendations: list[dict[str, Any]], context_awareness`
- `pipeline/intelligence_pipeline.py:608` — `def _preview_related_recommendations(recommendations: list[dict[str, Any]], preview_subject: str, *, candidate`
- `pipeline/intelligence_state.py:2311` — `def _alias_source_recommendations(state: Mapping[str, Any]) -> Any:`
- `pipeline/intelligence_state.py:2407` — `def _matches_recommendations(value: Any) -> bool:`
- `pipeline/performance_aggregator.py:85` — `recommendation = _copy_mapping(prediction_payload.get("recommendation"))`
- `pipeline/performance_aggregator.py:106` — `"recommendation": recommendation,`
- `pipeline/performance_aggregator.py:112` — `def _latest_by_recommendation_id(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:129` — `def _first_recommendation(result: Any) -> dict[str, Any]:`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:287` — `"recommendation": None,`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:311` — `"recommendation": _candidate_prose(top) or explanation.get("summary"),`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:381` — `"recommendation": _candidate_prose(row),`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:508` — `"recommendation": _candidate_prose(item),`
- ...and 108 more

**`shortlist`** — 8 site(s)

- `pipeline/intelligence_state.py:1582` — `shortlist = read_layer2_shortlist(requested_date)`
- `pipeline/intelligence_state.py:3528` — `shortlist = build_layer2_shortlist(normalized_date, list(manifests.keys()))`
- `pipeline/layer2_shortlist.py:259` — `shortlist = select_shortlist(opportunities)`
- `pipeline/layer2_shortlist.py:261` — `shortlist = select_shortlist(opportunities, horizon_days=horizon_days)`
- `syndicate/blueprints/intelligence.py:2673` — `shortlist = read_layer2_shortlist(selected_date)`
- `syndicate/blueprints/intelligence.py:2676` — `shortlist = None`
- `syndicate/blueprints/intelligence.py:2685` — `shortlist = (state or {}).get("layer2_shortlist")`
- `syndicate/features/shared/layer2_board.py:1402` — `def select_shortlist(`

**`board`** — 163 site(s)

- `pipeline/intelligence_state.py:116` — `def _board_window_days() -> int:`
- `pipeline/intelligence_state.py:121` — `def _board_window_candidate_dates(today: str | None = None) -> list[str]:`
- `pipeline/intelligence_state.py:138` — `def _default_board_window_dates(today: str | None = None) -> list[str]:`
- `pipeline/intelligence_state.py:421` — `def _board_build_deferral_reason(*, consecutive_odds_defers: int, consecutive_sim_defers: int = 0) -> str | No`
- `pipeline/intelligence_state.py:522` — `def _board_build_has_memory_headroom() -> bool:`
- `pipeline/intelligence_state.py:536` — `def _board_build_min_headroom_bytes() -> int:`
- `pipeline/intelligence_state.py:658` — `def _empty_board_protection_window_seconds() -> int:`
- `pipeline/intelligence_state.py:698` — `def _record_good_board_write(selected_date: str, candidate_count: int, written_at: str) -> None:`
- `pipeline/intelligence_state.py:710` — `def _last_good_board_write(selected_date: str) -> tuple[str, int] | None:`
- `pipeline/intelligence_state.py:721` — `def _last_board_write_from_history(selected_date: str) -> tuple[str, int] | None:`
- `pipeline/intelligence_state.py:775` — `def _empty_write_would_clobber_good_board(incoming: dict[str, Any]) -> bool:`
- `pipeline/intelligence_state.py:831` — `def _look_ahead_board_builds_enabled() -> bool:`
- ...and 151 more

**`snapshot`** — 229 site(s)

- `pipeline/intelligence_state.py:530` — `snapshot = memory_headroom_snapshot(_board_build_min_headroom_bytes())`
- `pipeline/intelligence_state.py:611` — `def _budgeted_snapshots_payload(snapshots_payload: dict[str, dict[str, Any]], latest_key: str | None) -> dict[`
- `pipeline/intelligence_state.py:874` — `def _snapshot_sport(snapshot: "IntelligenceSnapshot") -> str | None:`
- `pipeline/intelligence_state.py:904` — `def _snapshot_limit_matches(snapshot: "IntelligenceSnapshot", payload: dict[str, Any]) -> bool:`
- `pipeline/intelligence_state.py:923` — `def _snapshot_matches_payload(snapshot: "IntelligenceSnapshot", payload: dict[str, Any]) -> bool:`
- `pipeline/intelligence_state.py:946` — `def _effective_snapshot_date(snapshot: "IntelligenceSnapshot") -> str | None:`
- `pipeline/intelligence_state.py:979` — `def _snapshot_matches_requested_date(snapshot: "IntelligenceSnapshot", requested_date: str | None) -> bool:`
- `pipeline/intelligence_state.py:1402` — `def _snapshot_state_meta(snapshot: "IntelligenceSnapshot | None", *, source: str | None = None, run_key: str |`
- `pipeline/intelligence_state.py:1522` — `def _intelligence_board_snapshot_payload(state: dict[str, Any], *, selected_date: str | None = None) -> dict[s`
- `pipeline/intelligence_state.py:2633` — `def _board_snapshot_persist_payload(`
- `pipeline/intelligence_state.py:3272` — `snapshot = memory_headroom_snapshot(floor_bytes)`
- `pipeline/intelligence_state.py:5025` — `snapshot = self._snapshots.get(key)`
- ...and 217 more

## §7. Neutral-default pattern — absent data made indistinguishable from measured

### 0.5 substituted for a probability — 40 site(s)

- `syndicate/features/intelligence_audit.py:208` — `"confidence": _normalize_probability(recommendation.get("confidence") or record.get("confidence")) or _normali`
- `syndicate/features/intelligence_audit.py:247` — `"confidence": _normalize_probability(recommendation.get("confidence")) or _normalize_probability(recommendatio`
- `syndicate/features/intelligence_audit.py:282` — `"confidence": _normalize_probability(record.get("confidence")) or 0.5,`
- `syndicate/features/intelligence_audit.py:366` — `confidence = _normalize_probability((prediction.get("market_context") or {}).get("model_probability")) or 0.5`
- `syndicate/features/simulation_engine.py:322` — `confidence = _clamp(_coerce_float(context.get("confidence")) or 0.5, 0.0, 1.0)`
- `syndicate/features/simulation_engine.py:357` — `push_threshold = _coerce_float(context.get("push_threshold")) or 0.5`
- `syndicate/features/football/sim_engine/smartsim2/drive_priors.py:136` — `score += ((success_rate or 0.5) - 0.5) * 1.2`
- `syndicate/features/football/sim_engine/smartsim2/drive_priors.py:137` — `score += ((red_zone_efficiency or 0.5) - 0.5) * 0.8`
- `syndicate/features/football/sim_engine/smartsim2/drive_priors.py:139` — `score += ((pass_rate or 0.5) - 0.5) * 0.6`
- `syndicate/features/football/sim_engine/smartsim2/drive_priors.py:142` — `score += ((returning or 0.5) - 0.5) * 0.45`
- `syndicate/features/football/sim_engine/smartsim2/drive_priors.py:143` — `score += ((coach or 0.5) - 0.5) * 0.35`
- `syndicate/features/football/sim_engine/smartsim2/drive_priors.py:155` — `score += (0.5 - (success_rate_allowed or 0.5)) * 1.2`
- `syndicate/features/football/sim_engine/smartsim2/drive_priors.py:189` — `return 0.5`
- `syndicate/features/football/sim_engine/smartsim2/drive_priors.py:196` — `return 0.5`
- `syndicate/features/football/sim_engine/smartsim2/drive_priors.py:225` — `score += ((confidence or 0.5) - 0.5) * 0.5`
- `syndicate/features/nba/cards.py:439` — `return 0.5, 0.5`
- `syndicate/features/nba/cards.py:1733` — `return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))`
- `syndicate/features/ncaaf/cards.py:771` — `edge_strength = abs((win_probability or 0.5) - 0.5)`
- `syndicate/features/nhl/sim_engine/hockeysim/contracts.py:27` — `faceoff_win_pct: float = 0.5`
- `syndicate/features/nhl/sim_engine/hockeysim/engine.py:133` — `float(getattr(rates.home, "faceoff_win_pct", 0.5) or 0.5),`
- `syndicate/features/nhl/sim_engine/hockeysim/engine.py:133` — `float(getattr(rates.home, "faceoff_win_pct", 0.5) or 0.5),`
- `syndicate/features/nhl/sim_engine/hockeysim/engine.py:134` — `float(getattr(rates.away, "faceoff_win_pct", 0.5) or 0.5),`
- `syndicate/features/nhl/sim_engine/hockeysim/engine.py:134` — `float(getattr(rates.away, "faceoff_win_pct", 0.5) or 0.5),`
- `syndicate/features/nhl/sim_engine/hockeysim/engine.py:954` — `float(getattr(rates.home, "faceoff_win_pct", 0.5) or 0.5),`
- `syndicate/features/nhl/sim_engine/hockeysim/engine.py:954` — `float(getattr(rates.home, "faceoff_win_pct", 0.5) or 0.5),`
- ...and 15 more

### 50.0 / 50 substituted for a percentage — 3 site(s)

- `syndicate/features/shared/game_board_contract.py:319` — `away_pct = _safe_float(row.get("away_pct")) or 50.0`
- `syndicate/features/shared/game_board_contract.py:336` — `"away_pct": float(row.get("away_pct") or 50.0),`
- `syndicate/features/shared/game_board_contract.py:337` — `"home_pct": float(row.get("home_pct") or 50.0),`

### bare except: pass (failure indistinguishable from success) — 240 site(s)

- `pipeline/intelligence_pipeline.py:187` — `except Exception:`
- `pipeline/intelligence_state.py:3287` — `except Exception:`
- `pipeline/intelligence_state.py:3640` — `except Exception:`
- `pipeline/intelligence_state.py:5250` — `except Exception:`
- `pipeline/intelligence_state.py:5435` — `except Exception:`
- `pipeline/intelligence_state.py:5630` — `except Exception:`
- `syndicate/app.py:121` — `except Exception:`
- `syndicate/app.py:126` — `except OSError:`
- `syndicate/local_nhl_odds.py:155` — `except Exception:`
- `syndicate/local_nhl_odds.py:426` — `except Exception:`
- `syndicate/local_nhl_odds.py:470` — `except Exception:`
- `syndicate/local_nhl_odds.py:617` — `except Exception:`
- `syndicate/local_nhl_odds.py:623` — `except Exception:`
- `syndicate/local_nhl_odds.py:678` — `except Exception:`
- `syndicate/local_nhl_odds.py:827` — `except Exception:`
- `syndicate/blueprints/ask_the_syndicate.py:296` — `except Exception:`
- `syndicate/blueprints/ask_the_syndicate_data.py:2705` — `except Exception:`
- `syndicate/blueprints/home.py:1376` — `except Exception:`
- `syndicate/blueprints/home.py:2870` — `except Exception:`
- `syndicate/blueprints/home.py:2893` — `except Exception:`
- `syndicate/blueprints/home.py:2923` — `except Exception:`
- `syndicate/blueprints/home.py:2933` — `except Exception:`
- `syndicate/blueprints/home.py:3214` — `except Exception:`
- `syndicate/blueprints/home.py:3249` — `except Exception:`
- `syndicate/blueprints/home.py:3262` — `except Exception:`
- ...and 215 more

### .get(key, <plausible non-empty default>) — 20 site(s)

- `pipeline/intelligence_pipeline.py:471` — `if readiness_gate and not bool(readiness_gate.get("ok", True)):`
- `pipeline/intelligence_pipeline.py:703` — `if readiness_gate and not bool(readiness_gate.get("ok", True)):`
- `pipeline/intelligence_pipeline.py:713` — `if readiness_gate and not bool(readiness_gate.get("ok", True)):`
- `pipeline/intelligence_pipeline.py:800` — `if readiness_gate and not bool(readiness_gate.get("ok", True)):`
- `pipeline/intelligence_state.py:3276` — `if snapshot is None or snapshot.get("sufficient", True):`
- `syndicate/blueprints/intelligence.py:1948` — `persist = bool(payload.get("persist", True))`
- `syndicate/features/intelligence.py:2588` — `if snapshot is None or snapshot.get("sufficient", True):`
- `syndicate/features/intelligence.py:9154` — `if readiness_gate and not bool(readiness_gate.get("ok", True)):`
- `syndicate/features/mlb/betting_card.py:330` — `out["found"] = bool(out.get("found", True))`
- `syndicate/features/mlb/betting_card.py:350` — `out["found"] = bool(out.get("found", True))`
- `syndicate/features/mlb/cards.py:1176` — `include_base_over=bool(cfg.get("include_base_over", True)),`
- `syndicate/features/nhl/sim_engine/hockeysim/engine.py:670` — `cal_pp_sh_mult = _f((special_teams_cal or {}).get("pp_shot_multiplier", 1.0), 1.0)`
- `syndicate/features/nhl/sim_engine/hockeysim/engine.py:671` — `cal_pk_sh_mult = _f((special_teams_cal or {}).get("pk_shot_multiplier", 1.0), 1.0)`
- `syndicate/features/nhl/sim_engine/hockeysim/engine.py:672` — `cal_pp_gl_mult = _f((special_teams_cal or {}).get("pp_goal_multiplier", 1.0), 1.0)`
- `syndicate/features/nhl/sim_engine/hockeysim/engine.py:673` — `cal_pk_gl_mult = _f((special_teams_cal or {}).get("pk_goal_multiplier", 1.0), 1.0)`
- `syndicate/features/shared/basketball_props_smart_sim.py:2295` — `if not bool(signal_guard.get("ok", True)):`
- `syndicate/features/shared/live_refresh_loop.py:1939` — `if headroom is not None and not headroom.get("sufficient", True):`
- `syndicate/features/shared/live_refresh_loop.py:2063` — `if join_headroom is not None and not join_headroom.get("sufficient", True):`
- `syndicate/features/shared/live_refresh_loop.py:2955` — `if headroom is not None and not headroom.get("sufficient", True):`
- `syndicate/features/shared/live_refresh_loop.py:3074` — `if headroom is not None and not headroom.get("sufficient", True):`

### or <numeric fallback> on a model quantity — 4 site(s)

- `syndicate/features/football/sim_engine/smartsim2/drive_priors.py:225` — `score += ((confidence or 0.5) - 0.5) * 0.5`
- `syndicate/features/nba/cards.py:2087` — `p_home_win, p_away_win = sim_home_win_prob, 1.0 - sim_home_win_prob`
- `syndicate/features/ncaaf/cards.py:771` — `edge_strength = abs((win_probability or 0.5) - 0.5)`
- `syndicate/features/soccer/sim_engine/soccersim/possession_priors.py:194` — `score += ((confidence or 0.5) - 0.5) * 0.5`

### Filters that silently no-op on empty input — 388 site(s)

`if not x: return x` means a filter that matches nothing returns everything, and a caller cannot tell 'nothing to filter' from 'filter did not run'.

- `pipeline/evidence_builder.py:41` — `if not data:`
- `pipeline/intelligence_models.py:44` — `if not text:`
- `pipeline/intelligence_models.py:75` — `if not payload:`
- `pipeline/intelligence_models.py:167` — `if not payload:`
- `pipeline/intelligence_pipeline.py:167` — `if not text:`
- `pipeline/intelligence_pipeline.py:411` — `if not recommendations:`
- `pipeline/intelligence_state.py:283` — `if not value:`
- `pipeline/intelligence_state.py:767` — `if not written_at:`
- `pipeline/intelligence_state.py:995` — `if not text:`
- `pipeline/intelligence_state.py:1303` — `if not parsed_values:`
- `pipeline/intelligence_state.py:1342` — `if not current:`
- `pipeline/intelligence_state.py:1435` — `if not current:`
- `pipeline/intelligence_state.py:1944` — `if not normalized_date:`
- `pipeline/intelligence_state.py:1955` — `if not normalized_date:`
- `pipeline/intelligence_state.py:1964` — `if not selected_date:`
- `pipeline/intelligence_state.py:1976` — `if not normalized_date:`
- `pipeline/intelligence_state.py:3469` — `if not normalized_date:`
- `pipeline/performance_aggregator.py:41` — `if not text:`
- `syndicate/local_nhl_odds.py:530` — `if not commence_time_iso:`
- `syndicate/blueprints/ask_the_syndicate_data.py:219` — `if not candidates:`
- `syndicate/blueprints/ask_the_syndicate_data.py:257` — `if not found:`
- `syndicate/blueprints/ask_the_syndicate_data.py:339` — `if not loaded:`
- `syndicate/blueprints/ask_the_syndicate_data.py:502` — `if not best:`
- `syndicate/blueprints/ask_the_syndicate_data.py:619` — `if not rows:`
- `syndicate/blueprints/ask_the_syndicate_data.py:682` — `if not loaded:`

## §5 CORRECTION — the table above over-counts. Use THIS one.

**The first table counted `"term":` dict-literal keys as definitions. Those are USAGES.** Counting them produced `value = 1220 definitions`, which is not a finding, it is a pattern matching every dict in the codebase that happens to have a `value` key. Published anyway in the section above so the error is auditable; **the table below is the one to use.**

FUNCTION-DEFINITION sites only — a function whose NAME contains the term, i.e. somewhere that computes it. Still imperfect (a function can own a concept without naming it) but it does not confuse using a word with defining it.

| term | functions defining it | verdict |
|---|---:|---|
| `edge` | 69 | **NO OWNER** |
| `value` | 114 | **NO OWNER** |
| `ev` | 181 | **NO OWNER** |
| `model_edge_pct` | 2 | single owner |
| `min_value_pct` | 0 | no function owns this name |
| `fair_probability` | 4 | **contested** |
| `market_probability` | 1 | single owner |
| `implied_probability` | 9 | **NO OWNER** |
| `confidence` | 11 | **NO OWNER** |
| `score` | 138 | **NO OWNER** |
| `model_skill` | 0 | no function owns this name |
| `candidate` | 180 | **NO OWNER** |
| `opportunity` | 5 | **contested** |
| `selection` | 16 | **NO OWNER** |
| `pick` | 50 | **NO OWNER** |
| `recommendation` | 74 | **NO OWNER** |
| `shortlist` | 1 | single owner |
| `board` | 150 | **NO OWNER** |
| `snapshot` | 173 | **NO OWNER** |

### Sites for the contested terms

**`edge`**

- `pipeline/intelligence_state.py:1840` — `def _normalize_card_edge_units(`
- `pipeline/intelligence_state.py:1889` — `def intelligence_ledger_recording_enabled(`
- `pipeline/intelligence_state.py:1980` — `def _canonical_board_state_ledger_fingerprint_path(`
- `pipeline/intelligence_state.py:1992` — `def _record_canonical_board_state_ledger_fingerprint(`
- `pipeline/intelligence_state.py:1999` — `def maybe_record_board_state_to_evaluation_ledger(`
- `pipeline/performance_aggregator.py:75` — `def _normalized_prediction_ledger_records(`
- `syndicate/blueprints/ask_the_syndicate_data.py:3271` — `def _board_min_edge_pct(`
- `syndicate/blueprints/home.py:927` — `def _edge_text(`
- `syndicate/blueprints/home.py:2086` — `def _candidate_edge_fraction(`
- `syndicate/blueprints/ops.py:1789` — `def api_ops_sim_run_ledger(`
- `syndicate/features/bankroll_manager.py:87` — `def _candidate_edge(`
- `syndicate/features/intelligence.py:8204` — `def _candidate_betting_edge_components(`
- `syndicate/features/intelligence.py:8211` — `def _candidate_betting_edge_profile(`
- `syndicate/features/intelligence.py:8704` — `def build_edge_board_view(`
- ...and 55 more

**`value`**

- `pipeline/evidence_builder.py:30` — `def _first_value(`
- `pipeline/intelligence_state.py:2523` — `def _compress_oversized_values(`
- `pipeline/intelligence_state.py:2592` — `def _decompress_oversized_values(`
- `pipeline/intelligence_state.py:3614` — `def _candidate_numeric_value(`
- `pipeline/intelligence_state.py:3631` — `def _candidate_timestamp_value(`
- `syndicate/blueprints/ask_the_syndicate.py:141` — `def payload_value(`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:27` — `def _result_value(`
- `syndicate/blueprints/home.py:184` — `def _git_value(`
- `syndicate/blueprints/home.py:342` — `def _score_value(`
- `syndicate/blueprints/home.py:357` — `def _numeric_value(`
- `syndicate/blueprints/home.py:381` — `def _metric_or_tile_value(`
- `syndicate/blueprints/home.py:986` — `def _metric_value(`
- `syndicate/blueprints/home.py:1045` — `def _pill_value_text(`
- `syndicate/blueprints/home.py:1795` — `def _mlb_prop_actual_value(`
- ...and 100 more

**`ev`**

- `pipeline/evidence_builder.py:37` — `def _evidence_from_payload(`
- `pipeline/evidence_builder.py:120` — `def build_evidence_records(`
- `pipeline/evidence_builder.py:159` — `def attach_evidence(`
- `pipeline/intelligence_models.py:325` — `def build_evaluation_record(`
- `pipeline/intelligence_pipeline.py:96` — `def _log_json_event(`
- `pipeline/intelligence_pipeline.py:260` — `def _odds_control_plane_evidence(`
- `pipeline/intelligence_pipeline.py:310` — `def _comparison_evidence(`
- `pipeline/intelligence_pipeline.py:358` — `def _cross_sport_evidence(`
- `pipeline/intelligence_pipeline.py:406` — `def _recommendation_evidence(`
- `pipeline/intelligence_pipeline.py:562` — `def _normalize_preview_text(`
- `pipeline/intelligence_pipeline.py:566` — `def _preview_candidate_score(`
- `pipeline/intelligence_pipeline.py:606` — `def _preview_related_recommendations(`
- `pipeline/intelligence_pipeline.py:651` — `def _build_game_preview_response(`
- `pipeline/intelligence_pipeline.py:984` — `def _dedupe_evidence_records(`
- ...and 167 more

**`fair_probability`**

- `syndicate/features/shared/opportunity_signals.py:171` — `def fair_probability_by_book(`
- `syndicate/features/shared/opportunity_signals.py:201` — `def consensus_fair_probability(`
- `syndicate/features/shared/recommendation_engine.py:696` — `def _market_fair_probability(`
- `syndicate/features/shared/recommendation_engine.py:772` — `def _fair_probability(`

**`implied_probability`**

- `syndicate/features/bankroll_manager.py:49` — `def _implied_probability_from_odds(`
- `syndicate/features/intelligence.py:814` — `def _american_implied_probability(`
- `syndicate/features/intelligence.py:822` — `def odds_to_implied_probability(`
- `syndicate/features/shared/intelligence_evaluation.py:1360` — `def _implied_probability_from_american(`
- `syndicate/features/shared/odds_book_quotes.py:903` — `def _implied_probability(`
- `syndicate/features/shared/odds_lifecycle.py:769` — `def _implied_probability_from_american_odds(`
- `syndicate/features/shared/odds_refresh_tracking.py:231` — `def _implied_probability_from_american(`
- `syndicate/features/shared/opportunity_signals.py:43` — `def implied_probability(`
- `syndicate/features/shared/quote_enrichment.py:75` — `def _implied_probability(`

**`confidence`**

- `syndicate/features/bankroll_manager.py:58` — `def _confidence_scale(`
- `syndicate/features/intelligence.py:8332` — `def _candidate_confidence(`
- `syndicate/features/intelligence.py:9017` — `def _confidence_value_from_candidate(`
- `syndicate/features/ncaab/mirror_export.py:82` — `def _confidence_from_edge(`
- `syndicate/features/nfl/cards.py:78` — `def _confidence_rank(`
- `syndicate/features/nfl/picks.py:69` — `def _confidence(`
- `syndicate/features/shared/intelligence_evaluation.py:1594` — `def _confidence_tier(`
- `syndicate/features/shared/intelligence_evaluation.py:2068` — `def adjust_confidence(`
- `syndicate/features/shared/odds_framework.py:44` — `def _candidate_confidence(`
- `syndicate/features/shared/opportunity_signals.py:385` — `def _book_confidence(`
- `syndicate/features/shared/recommendation_engine.py:559` — `def _confidence_bucket_row(`

**`score`**

- `pipeline/intelligence_pipeline.py:566` — `def _preview_candidate_score(`
- `pipeline/intelligence_state.py:1725` — `def _score(`
- `pipeline/intelligence_state.py:3933` — `def _candidate_preliminary_scores(`
- `pipeline/intelligence_state.py:4234` — `def _attach_adjusted_scores(`
- `syndicate/local_nhl_odds.py:135` — `def _nhl_scoreboard_line(`
- `syndicate/local_nhl_odds.py:271` — `def scoreboard_day(`
- `syndicate/local_nhl_odds.py:300` — `def write_scoreboard_snapshot(`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:581` — `def _recommendation_relevance_score(`
- `syndicate/blueprints/ask_the_syndicate_data.py:297` — `def _mlb_game_score(`
- `syndicate/blueprints/ask_the_syndicate_data.py:928` — `def _boxscore_row_stats(`
- `syndicate/blueprints/ask_the_syndicate_data.py:964` — `def _boxscore_last_n(`
- `syndicate/blueprints/ask_the_syndicate_router.py:22` — `def score_question(`
- `syndicate/blueprints/ask_the_syndicate_router.py:198` — `def _base_score(`
- `syndicate/blueprints/home.py:342` — `def _score_value(`
- ...and 124 more

**`candidate`**

- `pipeline/intelligence_pipeline.py:566` — `def _preview_candidate_score(`
- `pipeline/intelligence_state.py:119` — `def _board_window_candidate_dates(`
- `pipeline/intelligence_state.py:197` — `def _candidate_has_price(`
- `pipeline/intelligence_state.py:215` — `def _default_unbounded_candidate_cap(`
- `pipeline/intelligence_state.py:1146` — `def _intelligence_state_candidate_count(`
- `pipeline/intelligence_state.py:1511` — `def _intelligence_state_daily_candidates(`
- `pipeline/intelligence_state.py:3290` — `def _abort_build_candidate_pool_if_memory_critical(`
- `pipeline/intelligence_state.py:3605` — `def _merge_candidate_pools(`
- `pipeline/intelligence_state.py:3614` — `def _candidate_numeric_value(`
- `pipeline/intelligence_state.py:3631` — `def _candidate_timestamp_value(`
- `pipeline/intelligence_state.py:3654` — `def _rank_fallback_candidates(`
- `pipeline/intelligence_state.py:3874` — `def _candidate_pool_key(`
- `pipeline/intelligence_state.py:3882` — `def _candidate_id(`
- `pipeline/intelligence_state.py:3889` — `def _candidate_raw_inputs(`
- ...and 166 more

**`opportunity`**

- `syndicate/blueprints/opportunity_board.py:56` — `def opportunity_board(`
- `syndicate/blueprints/opportunity_board.py:72` — `def api_opportunity_board(`
- `syndicate/blueprints/ops.py:311` — `def api_ops_opportunity_contract_status(`
- `syndicate/features/intelligence.py:179` — `def _normalize_opportunity_item(`
- `syndicate/features/intelligence.py:259` — `def _normalize_opportunity_list(`

**`selection`**

- `syndicate/features/correlation_engine.py:82` — `def _candidate_selection_direction(`
- `syndicate/features/intelligence.py:3193` — `def _candidate_selection_text(`
- `syndicate/features/intelligence.py:7107` — `def _candidate_selection_direction(`
- `syndicate/features/intelligence.py:8316` — `def _greedy_low_correlation_selection(`
- `syndicate/features/intelligence_audit.py:166` — `def _record_selection(`
- `syndicate/features/intelligence_audit.py:307` — `def _selection_subject(`
- `syndicate/features/intelligence_board.py:327` — `def _selection_side(`
- `syndicate/features/mlb/cards.py:3035` — `def _selection_live_edge(`
- `syndicate/features/mlb/hr_targets.py:719` — `def _hr_selection_rationale(`
- `syndicate/features/shared/daily_update_simulation_contract.py:16` — `def _default_selection_for_sport(`
- `syndicate/features/shared/odds_book_quotes.py:1423` — `def _selection_matches(`
- `syndicate/features/shared/odds_lifecycle.py:760` — `def _selection_direction(`
- `syndicate/features/shared/quote_enrichment.py:252` — `def _selection_hint(`
- `syndicate/features/shared/recommendation_engine.py:686` — `def _selection(`
- ...and 2 more

**`pick`**

- `syndicate/blueprints/ask_the_syndicate_data.py:932` — `def pick(`
- `syndicate/blueprints/home.py:1882` — `def _player_name_from_prop_pick_text(`
- `syndicate/blueprints/home.py:1914` — `def _market_label_from_pick_text(`
- `syndicate/blueprints/home.py:2073` — `def _candidate_pick_text(`
- `syndicate/blueprints/intelligence.py:1354` — `def _adjust_pick_for_profile(`
- `syndicate/blueprints/nba.py:827` — `def picks(`
- `syndicate/blueprints/nba.py:834` — `def api_picks(`
- `syndicate/blueprints/ncaaf.py:130` — `def picks(`
- `syndicate/blueprints/ncaaf.py:178` — `def api_picks(`
- `syndicate/blueprints/nfl.py:159` — `def picks(`
- `syndicate/blueprints/nfl.py:167` — `def api_picks(`
- `syndicate/blueprints/nhl.py:449` — `def picks(`
- `syndicate/blueprints/nhl.py:455` — `def api_picks(`
- `syndicate/blueprints/wnba.py:502` — `def picks(`
- ...and 36 more

**`recommendation`**

- `pipeline/intelligence_pipeline.py:406` — `def _recommendation_evidence(`
- `pipeline/intelligence_pipeline.py:606` — `def _preview_related_recommendations(`
- `pipeline/intelligence_state.py:2309` — `def _alias_source_recommendations(`
- `pipeline/intelligence_state.py:2406` — `def _matches_recommendations(`
- `pipeline/performance_aggregator.py:110` — `def _latest_by_recommendation_id(`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:127` — `def _first_recommendation(`
- `syndicate/blueprints/ask_the_syndicate_adapter.py:581` — `def _recommendation_relevance_score(`
- `syndicate/blueprints/home.py:864` — `def _game_market_recommendation_strings(`
- `syndicate/blueprints/home.py:3546` — `def _mlb_game_market_recommendation_rows(`
- `syndicate/blueprints/home.py:3675` — `def _nfl_game_market_recommendation_rows(`
- `syndicate/blueprints/home.py:3760` — `def _ncaaf_game_market_recommendation_rows(`
- `syndicate/blueprints/home.py:4455` — `def _pregame_prop_rows_from_mlb_recommendations(`
- `syndicate/blueprints/home.py:5102` — `def _prop_rows_from_props_recommendations_csv(`
- `syndicate/blueprints/home.py:5715` — `def _stamp_market_recommendations(`
- ...and 60 more

**`board`**

- `pipeline/intelligence_state.py:114` — `def _board_window_days(`
- `pipeline/intelligence_state.py:119` — `def _board_window_candidate_dates(`
- `pipeline/intelligence_state.py:136` — `def _default_board_window_dates(`
- `pipeline/intelligence_state.py:419` — `def _board_build_deferral_reason(`
- `pipeline/intelligence_state.py:520` — `def _board_build_has_memory_headroom(`
- `pipeline/intelligence_state.py:534` — `def _board_build_min_headroom_bytes(`
- `pipeline/intelligence_state.py:656` — `def _empty_board_protection_window_seconds(`
- `pipeline/intelligence_state.py:696` — `def _record_good_board_write(`
- `pipeline/intelligence_state.py:708` — `def _last_good_board_write(`
- `pipeline/intelligence_state.py:719` — `def _last_board_write_from_history(`
- `pipeline/intelligence_state.py:773` — `def _empty_write_would_clobber_good_board(`
- `pipeline/intelligence_state.py:829` — `def _look_ahead_board_builds_enabled(`
- `pipeline/intelligence_state.py:1005` — `def _board_contract_cards(`
- `pipeline/intelligence_state.py:1063` — `def _promote_board_contract_cards(`
- ...and 136 more

**`snapshot`**

- `pipeline/intelligence_state.py:609` — `def _budgeted_snapshots_payload(`
- `pipeline/intelligence_state.py:872` — `def _snapshot_sport(`
- `pipeline/intelligence_state.py:902` — `def _snapshot_limit_matches(`
- `pipeline/intelligence_state.py:921` — `def _snapshot_matches_payload(`
- `pipeline/intelligence_state.py:944` — `def _effective_snapshot_date(`
- `pipeline/intelligence_state.py:977` — `def _snapshot_matches_requested_date(`
- `pipeline/intelligence_state.py:1400` — `def _snapshot_state_meta(`
- `pipeline/intelligence_state.py:1520` — `def _intelligence_board_snapshot_payload(`
- `pipeline/intelligence_state.py:2631` — `def _board_snapshot_persist_payload(`
- `pipeline/intelligence_state.py:6218` — `def _snapshot_age_seconds(`
- `pipeline/intelligence_state.py:6765` — `def _decorate_intelligence_board_snapshot_response(`
- `pipeline/intelligence_state.py:6846` — `def _latest_non_empty_intelligence_board_snapshot_response(`
- `pipeline/intelligence_state.py:6878` — `def read_latest_intelligence_board_snapshot_response(`
- `syndicate/local_nhl_odds.py:300` — `def write_scoreboard_snapshot(`
- ...and 159 more


## §5 SECOND CORRECTION — the glossary CANNOT be built by pattern matching. Stop trying.

**Two mechanical attempts, both wrong, in opposite ways. Recorded in full so the
third person does not spend the same hour.**

1. Dict-key pattern (`"term":`) counted USAGES as definitions -> `value = 1220`.
2. Function-name substring (`def *term*(`) counts UNRELATED WORDS ->
   `ev = 181` matches `retrieve`, `level`, `event`, `evaluate`;
   `board = 150`, `snapshot = 173`, `candidate = 180`, `value = 114` the same way.

**Neither number belongs in a finding.** A short, common English word cannot be
counted by substring, and a concept can be owned by a function that never names
it. The brief calls this glossary "worth more than any single code fix" — which
is exactly why it must not be approximated by a regex.

### What IS trustworthy: the distinctive terms `[measured]`

Terms long or specific enough that substring collision is not credible:

| term | functions defining it | reading |
|---|---:|---|
| `model_skill` | **0** | nothing computes it by name; the `projection-skill-declaration` lane is adding it. A term the product uses that the engine does not own. |
| `min_value_pct` | **0** | a selection THRESHOLD with no defining function anywhere — it exists only as a config value read at use sites. |
| `market_probability` | 1 | single owner. |
| `shortlist` | 1 | single owner. |
| `fair_probability` | **4** | contested, and consistent with the model-audit lane's independent finding that three sites fall back to `confidence` as a model probability. |
| `implied_probability` | 9 | contested. |
| `confidence` | 11 | contested — and the brief records it being a scoring artefact in one place and read as P(outcome) in another. 11 definition sites is how that happens. |
| `model_edge_pct` | 2 | near-single owner. |
| `opportunity` | 5 | contested. |

**`fair_probability` (4) + `implied_probability` (9) + `confidence` (11) + the 18
prob<->odds conversions from Pass 1 = 42 places where a probability is defined or
converted.** That is the substrate under `edge`, `EV` and `value`, and it is the
most likely origin of the glossary collisions the brief lists — not three
independent bugs.

### How the glossary must actually be built

By reading, one term at a time, starting from the distinctive terms above and
following their call sites outward. `edge`/`value`/`EV`/`score`/`board` cannot be
approached by name at all; they have to be reached through the functions that
produce the numbers the UI renders. That is a deliberate, bounded piece of work
and it is the single highest-value item left in this audit.

## §4 and §6 ARE NOT DONE

Stated explicitly so the absence is not read as "nothing found".

- **§4 pipeline topology** (every stage from book quote to published row, twice —
  pregame and live, with latency per hop) — not attempted. This is the section
  that answers whether `14,216 -> 200 -> 145 -> 12 -> 5` is five deliberate
  stages or one plus four buffer sizes. It needs live tracing, not grep.
- **§6 state/artifact topology** (writer, readers, cadence, TTL, declared vs
  measured age for every artifact) — not attempted. The known
  `read_latest_intelligence_state` 7,346s-against-a-60s-SLA finding should be the
  entry point: enumerate its readers first.
- Both need a live system and a fresh context. Neither should be inferred from
  what is in this note.

## §4 PIPELINE TOPOLOGY — Layer 2 (the board web serves). Measured tonight.

**Provenance: every number here was measured on refresh-worker 2026-08-14 during
the layer2-freshness session, not re-derived for this audit.** Stage names are
`[from-code]`; cadences and counts are `[measured]`. The Layer 1 legacy pool and
the LIVE path are covered separately below and are thinner.

### Pregame stages, book quote -> published row

| # | stage | module | trigger | cadence `[measured]` |
|---|---|---|---|---|
| 1 | OddsAPI fetch | `scripts/fetch_<sport>_oddsapi_local.py` | `live_refresh_loop` launch | MLB **every ~121.6 min** |
| 2 | quote append | `odds_book_quotes.append_book_quotes` | end of fetch | ~20s after each launch |
| 3 | publish worker->web | `publish_hot_artifact` (streamed, no ceiling) | on append, `publish=True` default | per append |
| 4 | pull web->worker | `pull_hot_artifacts` + `pull_streamed_artifact` | board build / fast path | per build |
| 5 | grid build | `build_book_grid(quote_rows, last_seen=...)` | per shortlist build | per build |
| 6 | enrichment | `attach_game_state`, `attach_projections`, `attach_margin_model` | per build | per build |
| 7 | rank | `build_layer2_rows` | per build | per build |
| 8 | select | `select_shortlist` | per build | per build |
| 9 | cards | `layer2_rows_to_board_cards` | per build | per build |
| 10 | persist | `write_layer2_shortlist` -> `layer2_shortlist_<date>.json` | per build | per build |
| 11 | serve | web reads the artifact | per request | — |

**Stage 1 is the rate limiter for the whole pregame product.** Everything
downstream can run every 2 minutes and the prices will still be up to ~2 hours
old. Root cause measured: the pregame relaunch cooldown (1800s) is keyed by DATE
ONLY, not by sport, and sports rotate across launches, so MLB rides every 2nd-4th
one. Fix written, held on branch `odds/pregame-cooldown-per-sport`.

### The funnel — how much is deliberate `[measured]`

    14,195   opportunities_considered   (LAYER2_SHORTLIST, stable across builds)
       256   rows published
       112   rows on a 2-sport date

- **14,195 -> 256 IS a deliberate stage.** `select_shortlist`'s policy is
  documented in `pipeline/layer2_shortlist.py`: 100 per sport, floor 30 per kind,
  remainder on merit, unused floor flowing to the other kind. 4 sports x ~64
  gives the 256. On a 2-sport date it is 112. **It scales with sport count,
  which is what a policy looks like and not what a buffer looks like.**
- The brief's `200 -> 145 -> 12 -> 5` steps are NOT covered here. `145` and `12`
  live in the chat/evidence-pack path, which this audit has not traced.
- **`considered` was IDENTICAL (14,195) across five consecutive builds** and moved
  only when the underlying quote shard changed. So the top of the funnel is
  driven by stage 1's cadence, not by anything in stages 5-8.

### Layer 1 (legacy pool) — separate pipeline, same board

`build_intelligence_overview` (8 sports, hydrated) -> `collect_candidates` ->
`_score_candidates`/`filter_candidates` -> per-sport `candidate_pools` ->
`_merge_candidate_pools` -> `global_pool` -> board contract.

- **These two pipelines are independent and disagree.** `[measured]` On 3 of 5
  completed builds the Layer 1 pool returned `count=0` while Layer 2 returned
  256 rows on the SAME cycle. Layer 2 does not consume Layer 1's output.
- Layer 1 costs `candidate_collection_with_fallback` 498.7s per 3h and a hydrated
  overview that peaks at SUM-across-8-sports; Layer 2's whole build is 14-27s.
- **The most expensive stage in the board path feeds the pipeline that is not
  serving the board.** Whether Layer 1 still earns its cost is the single
  biggest open product question this audit has surfaced, and it is NOT answered
  here — `#385` already gated one of its fallbacks off on exactly this reasoning.

### LIVE path — thin, and mostly absent `[from prior measurement]`

- **No live GAME-LINE projection exists.** `predictions.full` in the live-lens
  snapshot is the PREGAME sim; all 6 final games in one sample carried pregame
  win probabilities. Only PROPS have a live tier.
- `rows_live_edged` has been 0 on every build to date, and the `live` bucket has
  never been observed against a live slate.
- So the brief's premise of "a pregame AND a live experience" is, on this
  evidence, **one experience plus a partial prop-only live tier**. Confirming
  that is §8's job and needs a live slate to observe.

### What §4 still owes

Latency per hop (stages 2-11 are unmeasured individually), the chat/evidence-pack
narrowing (`200 -> 145 -> 12 -> 5`), and the live path traced end to end on an
actual live slate. None can be grepped.
