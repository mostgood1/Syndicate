from __future__ import annotations
"""
CENTRAL DECISION ENGINE RULES

- All sports use the same candidate lifecycle
- No candidate is dropped solely for missing source
- Candidates must be normalized before scoring
- Tier classification replaces hard filtering
- Scoring must be centralized and sport-agnostic
"""

"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Serves the core intelligence layer and cached response state.

Constraints:
- State-driven execution
- Avoid redundant computation
"""

from difflib import SequenceMatcher
from datetime import date
from datetime import timedelta
from collections import OrderedDict
from functools import lru_cache
from itertools import combinations
import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
import re
import subprocess
from statistics import NormalDist
from typing import Any, Mapping

from flask import current_app

__path__ = [str(Path(__file__).with_name("intelligence"))]

from syndicate.blueprints.home import _build_sport_overview
from syndicate.blueprints.home import _build_prop_dashboard_row
from syndicate.blueprints.home import _game_bet_candidates_from_game
from syndicate.features.mlb.game_state import mlb_status_is_final as _mlb_status_is_final
from syndicate.features.mlb.game_state import mlb_status_is_live as _mlb_status_is_live
from syndicate.features.mlb.sources import daily_artifact_path as mlb_daily_artifact_path
from syndicate.features.mlb.sources import daily_snapshot_oddsapi_pitcher_props_path as mlb_daily_snapshot_oddsapi_pitcher_props_path
from syndicate.features.mlb.sources import daily_top_props_path as mlb_daily_top_props_path
from syndicate.features.mlb.sources import live_lens_report_path as mlb_live_lens_report_path
from syndicate.features.mlb.sources import load_json_file as mlb_load_json_file
from syndicate.features.nba.sources import live_snapshot_path as nba_live_snapshot_path
from syndicate.features.nba.sources import processed_path as nba_processed_path
from syndicate.features.nba.sources import season_betting_card_day_path as nba_season_betting_card_day_path
from syndicate.features.ncaaf import sources as ncaaf_sources
from syndicate.features.ncaab import sources as ncaab_sources
from syndicate.features.nfl import sources as nfl_sources
from syndicate.features.nhl.sources import processed_path as nhl_processed_path
from syndicate.features.nhl.sources import props_lines_snapshot_path as nhl_props_lines_snapshot_path
from syndicate.features.nhl.sources import recommendation_path as nhl_recommendation_path
from syndicate.features.nhl.sources import scoreboard_snapshot_path as nhl_scoreboard_snapshot_path
from syndicate.features.intelligence_analysis_views import build_analysis_views as _runtime_build_analysis_views
from syndicate.features.bankroll_manager import compute_bet_size as _compute_bet_size
from syndicate.features.bankroll_manager import build_portfolio as _build_portfolio
from syndicate.features.market_data import attach_market_data as _attach_market_data
from syndicate.features.simulation_engine import SimulationEngine
from syndicate.features.prediction_ledger import _signal_weight
from syndicate.features.shared.memory_observability import log_container_memory
from syndicate.features.shared.intelligence_evaluation import adjust_confidence
from syndicate.features.shared.intelligence_evaluation import build_feature_coverage_profile
from syndicate.features.shared.intelligence_evaluation import build_reliability_profile
from syndicate.features.shared.intelligence_contracts import UniversalCandidate
from syndicate.features.shared.recommendation_engine import filter_candidates as _shared_filter_candidates
from syndicate.features.shared.recommendation_engine import rank_recommendations as _shared_rank_recommendations
from syndicate.features.shared.ops_refresh import load_latest_refresh_status
from syndicate.features.shared.source_roots import preferred_artifact_roots
from syndicate.features.shared.odds_control_plane import load_odds_history_payload_for_sport as _canonical_load_odds_history_payload_for_sport
from syndicate.features.shared.odds_control_plane import resolve_current_shard_key
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.week_calendar import shard_key_for_week
from syndicate.features.intelligence_parlay_correlation import parlay_leg_market_key as _runtime_parlay_leg_market_key
from syndicate.features.intelligence_parlay_correlation import parlay_leg_market_shape as _runtime_parlay_leg_market_shape
from syndicate.features.intelligence_parlay_correlation import parlay_matches_preferences as _runtime_parlay_matches_preferences
from syndicate.features.intelligence_parlay_correlation import parlay_pair_penalty as _runtime_parlay_pair_penalty
from syndicate.features.intelligence_reasoning import build_analysis_brief as _runtime_build_analysis_brief
from syndicate.features.correlation_engine import compute_correlation as _compute_candidate_correlation
def _default_syndicate_sports() -> list[dict[str, Any]]:
    # #47. This is NOT a cosmetic default -- it is the list the WORKER
    # actually uses. _configured_syndicate_sports falls back here whenever
    # current_app raises (no Flask app context), and the intelligence loop
    # runs on refresh-worker outside any request context, so every candidate
    # the curated board is built from comes from this list rather than from
    # app.config["SYNDICATE_SPORTS"].
    #
    # Soccer was configured in syndicate/app.py all along and still never
    # appeared in Layer 2. Production traces settle why: candidate generation
    # ran for mlb, nba, wnba, nfl, ncaaf, ncaab, nhl -- this list, in this
    # exact order. app.py's order is mlb, nba, nhl, nfl, wnba, ncaaf, ncaab,
    # soccer, so the worker was provably taking the fallback.
    #
    # Keep this in sync with app.py's SYNDICATE_SPORTS slugs. A sport missing
    # here is invisible to the board no matter what the web app is configured
    # with, and it fails silently -- there is no error, the sport simply never
    # generates candidates.
    return [
        {"slug": "mlb", "name": "MLB", "primary_href": "/mlb", "primary_label": "Open MLB cards"},
        {"slug": "nba", "name": "NBA", "primary_href": "/nba", "primary_label": "Open NBA cards"},
        {"slug": "wnba", "name": "WNBA", "primary_href": "/wnba", "primary_label": "Open WNBA cards"},
        {"slug": "nfl", "name": "NFL", "primary_href": "/nfl", "primary_label": "Open NFL cards"},
        {"slug": "ncaaf", "name": "NCAAF", "primary_href": "/ncaaf", "primary_label": "Open NCAAF cards"},
        {"slug": "ncaab", "name": "NCAAB", "primary_href": "/ncaab", "primary_label": "Open NCAAB cards"},
        {"slug": "nhl", "name": "NHL", "primary_href": "/nhl", "primary_label": "Open NHL cards"},
        {"slug": "soccer", "name": "Soccer", "primary_href": "/soccer", "primary_label": "Open Soccer cards"},
    ]

def _configured_syndicate_sports() -> list[dict[str, Any]]:
    try:
        configured = current_app.config.get("SYNDICATE_SPORTS", [])
    except RuntimeError:
        return _default_syndicate_sports()
    if isinstance(configured, list) and configured:
        return [dict(sport) for sport in configured if isinstance(sport, dict)]
    return _default_syndicate_sports()
from syndicate.features.intelligence_parlay_runtime import build_parlay_payload as _runtime_build_parlay_payload
from syndicate.features.intelligence_parlay_runtime import build_parlays as _runtime_build_parlays
from syndicate.features.intelligence_parlay_runtime import build_round_robin_parlays as _runtime_build_round_robin_parlays
from syndicate.features.intelligence_parlay_runtime import parlay_rank_score as _runtime_parlay_rank_score
from syndicate.features.intelligence_router import analysis_focus_from_question as _runtime_analysis_focus_from_question
from syndicate.features.intelligence.api.response_builder import build_response
from syndicate.features.intelligence.scoring.edge import get_top_live_opportunities
from syndicate.features.intelligence.signals.normalization import _numeric_hint
from syndicate.features.intelligence.signals.normalization import _pct_hint
from syndicate.features.intelligence.signals.normalization import _safe_text
from syndicate.features.shared.artifact_manifests import load_artifact_manifests
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.wnba.sources import processed_path as wnba_processed_path
from syndicate.features.shared.intelligence_evaluation import build_intelligence_evaluation_bundle
from syndicate.features.intelligence_board import build_intelligence_board_contract
from syndicate.features.shared.simulation_adapter import build_simulation_engine_context_from_candidate


_SIMULATION_ENGINE = SimulationEngine()
MAX_CORRELATION_THRESHOLD = 0.65
logger = logging.getLogger(__name__)


def _intel_trace(event: str, **fields: Any) -> None:
    try:
        print(f"[INTEL_TRACE] {json.dumps({'event': event, **fields}, sort_keys=True, default=str)}", flush=True)
    except Exception:
        print(f"[INTEL_TRACE] {event}", flush=True)


def _intel_trace_timed(event: str, started_at: float, **fields: Any) -> None:
    payload = dict(fields)
    try:
        payload["duration_ms"] = round((time.perf_counter() - started_at) * 1000.0, 3)
    except Exception:
        pass
    _intel_trace(event, **payload)


def _cache_query_response(cache_key: str, response_payload: dict[str, Any]) -> None:
    return None


def _read_cached_query_response(cache_key: str) -> dict[str, Any] | None:
    return None


def _attach_intelligence_response_aliases(response: dict[str, Any]) -> dict[str, Any]:
    def _normalize_opportunity_item(item: Any) -> dict[str, Any]:
        payload = dict(item) if isinstance(item, dict) else {}
        selection = payload.get("selection") or payload.get("pick") or payload.get("name") or payload.get("label")
        market = payload.get("market") or payload.get("market_label") or payload.get("market_key")
        sport_slug = payload.get("sport_slug") or payload.get("sport")
        edge = payload.get("edge")
        if edge in {None, ""}:
            edge = payload.get("normalized_edge")
        score = payload.get("score")
        if score in {None, ""}:
            score = payload.get("adjusted_score") or payload.get("expected_value") or payload.get("ev_current") or 0.0
        payload["selection"] = selection
        # Do NOT overwrite an existing name with the selection. This helper adds
        # aliases; clobbering here destroyed the only human-readable label on the
        # item. Candidates built from a rail item carry name="Aaron Judge Over 0.5
        # Home Runs" and pick="Over 0.5", so the old line rendered them as bare
        # "Over 0.5" with no player -- while candidates built from an artifact
        # were unaffected, because their selection already IS the full label.
        # That inconsistency is why only some surfaces looked broken.
        # `selection` and `pick` both still carry the selection for consumers
        # that want it, and blueprints/intelligence.py:928 already falls back
        # name -> display_name -> selection, so nothing loses access to either.
        payload["name"] = payload.get("name") or selection
        payload["pick"] = selection
        payload["market"] = market
        payload["score"] = score
        payload["sport_slug"] = str(sport_slug or "").strip().lower() or None
        payload["edge"] = edge
        if payload.get("normalized_edge") in {None, ""} and edge not in {None, ""}:
            payload["normalized_edge"] = edge
        # Consumers read american_odds off these items (price displays, the
        # plus-money contract); only pool-serialized candidates carried it,
        # engine recommendations only carry the raw odds text.
        if payload.get("american_odds") is None:
            payload["american_odds"] = _american_odds_value(payload.get("odds"))
        if payload.get("subject_key") is None:
            payload["subject_key"] = _candidate_subject_key(payload)
        if payload.get("market_key") is None:
            payload["market_key"] = _candidate_market_key(payload)
        # _candidate_rationale builds the narrative sentence(s) from the raw
        # candidate fields (live projection vs line, edge, confidence, ...);
        # only _candidate_summary called it, and nothing serves items
        # through that path -- run_intelligence_query's flat recommendations
        # never had a "rationale" populated at all.
        if not _safe_text(payload.get("rationale"), ""):
            payload["rationale"] = _candidate_rationale(payload)
        # _score_candidates nests this under candidate["market_fit"]
        # ({"market_fit_score": ...}); several table/chart builders already
        # flatten it back out at read time (see the market_fit.get(...)
        # sites elsewhere in this file) -- do it once here instead.
        if payload.get("market_fit_score") is None:
            market_fit = payload.get("market_fit") if isinstance(payload.get("market_fit"), dict) else {}
            payload["market_fit_score"] = market_fit.get("market_fit_score")
        if payload.get("advanced_readiness") is None:
            payload["advanced_readiness"] = _readiness_label(payload.get("advanced_gate") or {})
        if payload.get("advanced_ready") is None:
            payload["advanced_ready"] = bool((payload.get("advanced_gate") or {}).get("ready"))
        if payload.get("missing_advanced_inputs") is None:
            payload["missing_advanced_inputs"] = [
                {
                    "label": _safe_text(item.get("label"), "Advanced input"),
                    "path": _safe_text(item.get("path"), "-"),
                    "missing_reason": _safe_text(item.get("missing_reason"), "missing"),
                }
                for item in ((payload.get("advanced_gate") or {}).get("missing_inputs") or [])[:3]
                if isinstance(item, dict)
            ]
        return payload

    def _normalize_opportunity_list(key: str) -> None:
        items = response.get(key)
        if isinstance(items, list):
            response[key] = [_normalize_opportunity_item(item) for item in items if isinstance(item, dict)]

    response["boardContract"] = dict(response.get("board_contract") or {})
    response["evaluationBundle"] = dict(response.get("evaluation_bundle") or {})
    performance_analytics = response.get("performance_analytics")
    if not isinstance(performance_analytics, dict) and isinstance(response.get("evaluation_bundle"), dict):
        performance_analytics = response.get("evaluation_bundle", {}).get("performance_analytics")
    response["performance_analytics"] = dict(performance_analytics or {})
    response["performanceAnalytics"] = dict(performance_analytics or {})
    response["policyControl"] = dict(response.get("policy_control") or {})
    response["recommendationHistory"] = dict(response.get("recommendation_history") or {})
    response["portfolioTracking"] = dict(response.get("portfolio_tracking") or {})
    response["portfolioEvents"] = dict(response.get("portfolio_events") or {})
    response["portfolioEventRecords"] = list(response.get("portfolio_event_records") or [])
    _normalize_opportunity_list("top_opportunities")
    _normalize_opportunity_list("recommendations")
    _normalize_opportunity_list("top_live_opportunities")

    nested_response = response.get("response")
    if isinstance(nested_response, dict):
        for key in ("top_opportunities", "recommendations", "top_live_opportunities"):
            nested_items = nested_response.get(key)
            if isinstance(nested_items, list):
                nested_response[key] = [_normalize_opportunity_item(item) for item in nested_items if isinstance(item, dict)]

    # board_contract/policy_control/etc. above are promoted because
    # IntelligenceStateService._compute_response (pipeline/intelligence_state.py)
    # sets them directly at this dict's own top level. analysis_views/
    # headline/summary/analysis_brief/supporting_evidence are NOT -- that
    # method only nests them inside response["analysis"] (== response["response"],
    # the same dict under two keys -- see its `response["response"] = analysis`
    # line). run_intelligence_query's OWN direct callers (e.g. Ask the
    # Syndicate) get these fields flat already; a request routed through
    # /api/intelligence/query's force_refresh path did not, silently making
    # them unreachable at the top level this response's other query-api
    # consumers (and every test asserting on them) expect. Promote them the
    # same way board_contract etc. already are, without overwriting a value
    # that's already present at this top level from some other path.
    nested_analysis = response.get("analysis") if isinstance(response.get("analysis"), dict) else (nested_response if isinstance(nested_response, dict) else {})
    if isinstance(nested_analysis, dict):
        for key in ("analysis_views", "headline", "summary", "analysis_brief", "supporting_evidence", "board_notes", "readiness_gate", "local_only"):
            if key not in response and key in nested_analysis:
                response[key] = nested_analysis[key]

    return response


def _query_cache_key(*, question: str, selected_date: str, mode: str | None, sport: str | None, game_state: str | None, limit: int | None, timing: str | None, include_props: bool | None, include_games: bool | None, policy: str | None, overview: list[dict[str, Any]]) -> str:
    payload = {
        "question": str(question or "").strip(),
        "selected_date": str(selected_date or "").strip(),
        "mode": str(mode or "").strip().lower(),
        "sport": str(sport or "").strip().lower(),
        "game_state": str(game_state or "").strip().lower(),
        "limit": int(limit) if limit is not None else None,
        "timing": str(timing or "").strip().lower(),
        "include_props": None if include_props is None else bool(include_props),
        "include_games": None if include_games is None else bool(include_games),
        "policy": str(policy or "").strip().lower() or None,
        "overview": overview,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_SPORT_KEYWORDS: dict[str, set[str]] = {
    "mlb": {"mlb", "baseball", "homer", "home run", "strikeout", "ks", "hits", "total bases", "rbi"},
    "nba": {"nba", "basketball", "points", "rebounds", "assists", "threes", "pra", "double-double"},
    "wnba": {"wnba", "women's basketball", "womens basketball", "threes", "pra", "points", "rebounds", "assists"},
    "nhl": {"nhl", "hockey", "shots", "saves", "goalie", "puck line", "goals", "assists"},
    "nfl": {"nfl", "football", "touchdown", "passing", "rushing", "receiving", "yards"},
    "ncaaf": {"ncaaf", "college football", "cfb", "touchdown", "passing", "rushing", "receiving", "yards"},
    "ncaab": {"ncaab", "college basketball", "cbb", "points", "rebounds", "assists", "threes"},
}

_PROP_MARKET_KEYWORDS = {
    "prop",
    "props",
    "player",
    "pts",
    "reb",
    "ast",
    "pra",
    "threes",
    "shots",
    "strikeout",
    "ks",
    "hits",
    "rbi",
    "yards",
    "touchdown",
}

_GAME_MARKET_KEYWORDS = {"moneyline", "ml", "spread", "side", "total", "game bet", "puck line"}
_DATE_TOKEN_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2}|\d{8})")
_PARLAY_LEG_WORDS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
}
_CONSERVATIVE_RISK_TOKENS = (
    "conservative",
    "safer",
    "safe",
    "safest",
    "low risk",
    "lower risk",
    "high confidence",
    "highest confidence",
    "most likely",
)
_AGGRESSIVE_RISK_TOKENS = ("aggressive", "longshot", "long shot", "high risk", "ceiling", "upside", "highest-upside")
_LOW_CORRELATION_TOKENS = ("low correlation", "uncorrelated", "independent", "diversified")
_MEDIUM_CORRELATION_TOKENS = ("medium correlation", "moderate correlation", "balanced correlation")
_HIGH_CORRELATION_TOKENS = ("high correlation", "correlated", "stacked", "stack", "same game", "same-game", "sgp")
_MARKET_FOCUS_ALIASES: dict[str, tuple[str, ...]] = {
    "home_runs": ("home runs", "home run", "homers", "homer", "hr"),
    "strikeouts": ("strikeouts", "strikeout", "pitcher strikeouts", "ks", "k props"),
    "total_bases": ("total bases", "total base", "batter total bases", "tb"),
    "moneyline": ("moneyline", "ml"),
    "spread": ("spread", "puck line"),
    "total": ("total", "game total", "totals"),
    "points": ("points", "point", "pts"),
    "rebounds": ("rebounds", "rebound", "rebs", "reb"),
    "assists": ("assists", "assist", "asts", "ast"),
    "threes": ("threes", "three pointers", "three pointer", "three point makes", "three point makes", "three point made", "3pm", "3ptm", "3 ptm", "3 point makes", "3 pointers", "3s"),
    "pra": ("pra", "points rebounds assists"),
    "shots": ("shots", "shots on goal", "sog"),
    "saves": ("saves", "save"),
    "goals": ("goals", "goal"),
    # Must precede "hits" below -- checked in insertion order, first match
    # wins, and every label variant of this stat ("Hitter H+R+R" from the
    # vendor sim spec's label, "Hits + Runs + RBIs" from daily_top_props'
    # statLabel, "hits_runs_rbis" from its stat key) contains the word
    # "hits", so without its own entry ahead of "hits" this composite stat
    # always misclassified as the plain single-stat Hits market. Confirmed
    # live 2026-08-01: daily_top_props candidates for this market resolved
    # market_key "hits" while live-lens's "Hitter H+R+R" rows independently
    # fell back to a THIRD, different key ("h_r_r") -- the two builders
    # never agreed on one key, so _mlb_pregame_mean_by_player_market's
    # cross-builder lookup always missed, leaving Layer 2's live-lens H+R+R
    # candidates permanently blank in "projected" even when daily_top_props
    # had a real mean for the same player+stat+game.
    "hits_runs_rbis": ("hits runs rbis", "hits+runs+rbis", "h+r+r", "hrr"),
    "hits": ("hits", "hit"),
    "rbi": ("rbi", "runs batted in"),
    "touchdowns": ("touchdowns", "touchdown", "td"),
    "passing_yards": ("passing yards",),
    "rushing_yards": ("rushing yards",),
    "receiving_yards": ("receiving yards",),
    "turnovers": ("turnovers", "turnover"),
    "steals": ("steals", "steal"),
    "blocks": ("blocks", "block"),
}
_MARKET_FOCUS_LABELS = {
    "home_runs": "Home runs",
    "strikeouts": "Strikeouts",
    "total_bases": "Total bases",
    "moneyline": "Moneyline",
    "spread": "Spread",
    "total": "Total",
    "points": "Points",
    "rebounds": "Rebounds",
    "assists": "Assists",
    "threes": "Threes",
    "pra": "PRA",
    "shots": "Shots",
    "saves": "Saves",
    "goals": "Goals",
    "hits_runs_rbis": "Hits+Runs+RBIs",
    "hits": "Hits",
    "rbi": "RBI",
    "touchdowns": "Touchdowns",
    "passing_yards": "Passing yards",
    "rushing_yards": "Rushing yards",
    "receiving_yards": "Receiving yards",
    "turnovers": "Turnovers",
    "steals": "Steals",
    "blocks": "Blocks",
}
_MARKET_FALLBACK_STOPWORDS = {
    "alt",
    "alternate",
    "batter",
    "bet",
    "bets",
    "game",
    "games",
    "hitter",
    "live",
    "market",
    "markets",
    "pitcher",
    "player",
    "players",
    "pregame",
    "prop",
    "props",
    "team",
}
_BINARY_CEILING_MARKETS = {"home_runs", "touchdowns"}
_VOLUME_PROP_MARKETS = {"strikeouts", "total_bases", "turnovers", "steals", "blocks", "hits", "rbi", "shots", "saves", "goals"}
_COUNTING_PROP_MARKETS = {"points", "rebounds", "assists", "threes", "pra", "passing_yards", "rushing_yards", "receiving_yards"}
_GAME_SIDE_MARKETS = {"moneyline", "spread", "total"}
_SPORT_MARKET_SHAPE_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    ("nba", "points"): {
        "shape_detail": "nba_usage_creation",
        "margin_weight": 4.3,
        "normalized_margin_weight": 12.8,
        "confidence_baseline": 55.5,
        "plus_money_bonus": 1.15,
    },
    ("nba", "assists"): {
        "shape_detail": "nba_playmaking_network",
        "margin_weight": 4.4,
        "normalized_margin_weight": 13.2,
        "confidence_baseline": 55.0,
        "plus_money_bonus": 1.2,
    },
    ("nba", "threes"): {
        "shape_detail": "nba_usage_creation",
        "margin_weight": 4.5,
        "normalized_margin_weight": 13.5,
        "confidence_baseline": 55.0,
        "plus_money_bonus": 1.25,
    },
    ("nba", "pra"): {
        "shape_detail": "nba_usage_creation",
        "margin_weight": 4.2,
        "normalized_margin_weight": 12.6,
        "confidence_baseline": 56.0,
        "plus_money_bonus": 1.1,
    },
    ("nba", "rebounds"): {
        "shape_detail": "nba_rebound_environment",
        "margin_weight": 4.15,
        "normalized_margin_weight": 12.4,
        "confidence_baseline": 55.0,
        "plus_money_bonus": 1.05,
    },
    ("wnba", "points"): {
        "shape_detail": "wnba_role_pressure",
        "margin_weight": 3.75,
        "normalized_margin_weight": 11.4,
        "confidence_baseline": 57.0,
        "plus_money_bonus": 0.9,
    },
    ("wnba", "assists"): {
        "shape_detail": "wnba_creation_stability",
        "margin_weight": 3.85,
        "normalized_margin_weight": 11.8,
        "confidence_baseline": 57.0,
        "plus_money_bonus": 0.95,
    },
    ("wnba", "threes"): {
        "shape_detail": "wnba_creation_stability",
        "margin_weight": 3.7,
        "normalized_margin_weight": 11.2,
        "confidence_baseline": 57.5,
        "plus_money_bonus": 0.85,
    },
    ("wnba", "pra"): {
        "shape_detail": "wnba_role_pressure",
        "margin_weight": 3.65,
        "normalized_margin_weight": 11.0,
        "confidence_baseline": 57.5,
        "plus_money_bonus": 0.85,
    },
    ("wnba", "rebounds"): {
        "shape_detail": "wnba_possession_pressure",
        "margin_weight": 3.95,
        "normalized_margin_weight": 12.1,
        "confidence_baseline": 56.5,
        "plus_money_bonus": 0.95,
    },
    ("ncaab", "points"): {
        "shape_detail": "ncaab_tempo_volatility",
        "margin_weight": 3.7,
        "normalized_margin_weight": 11.3,
        "confidence_baseline": 58.0,
        "plus_money_bonus": 0.8,
    },
    ("ncaab", "assists"): {
        "shape_detail": "ncaab_tempo_volatility",
        "margin_weight": 3.75,
        "normalized_margin_weight": 11.5,
        "confidence_baseline": 58.0,
        "plus_money_bonus": 0.8,
    },
    ("ncaab", "threes"): {
        "shape_detail": "ncaab_tempo_volatility",
        "margin_weight": 3.6,
        "normalized_margin_weight": 11.0,
        "confidence_baseline": 58.5,
        "plus_money_bonus": 0.75,
    },
    ("ncaab", "pra"): {
        "shape_detail": "ncaab_tempo_volatility",
        "margin_weight": 3.55,
        "normalized_margin_weight": 10.8,
        "confidence_baseline": 58.5,
        "plus_money_bonus": 0.7,
    },
    ("ncaab", "rebounds"): {
        "shape_detail": "ncaab_tempo_volatility",
        "margin_weight": 3.8,
        "normalized_margin_weight": 11.7,
        "confidence_baseline": 57.5,
        "plus_money_bonus": 0.85,
    },
}
_MEDIUM_CORRELATION_SHAPE_LIMITS = {
    "binary_ceiling_prop": 1,
    "game_market": 1,
    "counting_prop": 2,
    "volume_prop": 3,
    "general_market": 2,
}
_MEDIUM_CORRELATION_SPORT_SHAPE_LIMITS = {
    ("nba", "volume_prop"): 2,
    ("wnba", "volume_prop"): 2,
    ("ncaab", "volume_prop"): 2,
    ("nhl", "volume_prop"): 2,
}
_MEDIUM_CORRELATION_SPORT_MARKET_LIMITS = {
    ("mlb", "strikeouts"): 2,
    ("mlb", "total_bases"): 1,
}
_MEDIUM_CORRELATION_SPORT_MARKET_PAIR_BLOCKS = {
    ("nba", ("assists", "points")),
    ("wnba", ("assists", "points")),
    ("ncaab", ("assists", "points")),
}
_PARLAY_SPORT_MARKET_PAIR_PENALTIES = {
    ("mlb", ("hits", "total_bases")): 1.0,
    ("mlb", ("hits", "home_runs")): 1.2,
    ("mlb", ("hits", "rbi")): 1.15,
    ("mlb", ("home_runs", "total_bases")): 1.35,
    ("mlb", ("rbi", "total_bases")): 1.2,
    ("mlb", ("home_runs", "rbi")): 1.25,
    ("ncaaf", ("passing_yards", "rushing_yards")): 1.1,
    ("ncaaf", ("passing_yards", "receiving_yards")): 1.25,
    ("ncaaf", ("passing_yards", "touchdowns")): 1.3,
    ("ncaaf", ("receiving_yards", "rushing_yards")): 1.0,
    ("ncaaf", ("receiving_yards", "touchdowns")): 1.2,
    ("ncaaf", ("rushing_yards", "touchdowns")): 1.15,
    ("nfl", ("passing_yards", "rushing_yards")): 1.1,
    ("nfl", ("passing_yards", "receiving_yards")): 1.25,
    ("nfl", ("passing_yards", "touchdowns")): 1.3,
    ("nfl", ("receiving_yards", "rushing_yards")): 1.0,
    ("nfl", ("receiving_yards", "touchdowns")): 1.2,
    ("nfl", ("rushing_yards", "touchdowns")): 1.15,
    ("nhl", ("assists", "goals")): 1.15,
    ("nhl", ("assists", "shots")): 1.1,
    ("nhl", ("goals", "shots")): 1.25,
    ("nba", ("assists", "rebounds")): 1.6,
    ("nba", ("points", "rebounds")): 3.0,
    ("nba", ("points", "threes")): 1.5,
    ("wnba", ("assists", "rebounds")): 1.6,
    ("wnba", ("points", "rebounds")): 3.0,
    ("wnba", ("points", "threes")): 1.5,
    ("ncaab", ("assists", "rebounds")): 1.45,
    ("ncaab", ("points", "rebounds")): 2.5,
    ("ncaab", ("points", "threes")): 1.25,
}
_MARKET_SCRIPT_CLUSTERS = {
    "home_runs": "batter_production",
    "points": "usage",
    "assists": "usage",
    "threes": "usage",
    "turnovers": "usage",
    "passing_yards": "football_production",
    "rushing_yards": "football_production",
    "receiving_yards": "football_production",
    "touchdowns": "football_production",
    "total_bases": "batter_production",
    "hits": "batter_production",
    "rbi": "batter_production",
    "shots": "usage",
    "goals": "usage",
    "rebounds": "possession",
    "blocks": "possession",
    "steals": "possession",
}
_EXPLICIT_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS = {
    ("nba", ("possession", "usage")): 1.02,
    ("nba", ("usage", "usage")): 1.05,
    ("wnba", ("possession", "usage")): 1.02,
    ("wnba", ("usage", "usage")): 1.05,
    ("ncaab", ("possession", "usage")): 1.02,
    ("ncaab", ("usage", "usage")): 1.04,
}
_SCRIPT_CLUSTER_OPPOSING_DIRECTION_MULTIPLIERS = {
    ("mlb", ("batter_production", "batter_production")): 0.45,
    ("ncaaf", ("football_production", "football_production")): 0.45,
    ("nfl", ("football_production", "football_production")): 0.45,
}
_SCRIPT_CLUSTER_PAIR_FALLBACK_PENALTIES = {
    ("ncaaf", ("football_production", "football_production")): 1.0,
    ("nfl", ("football_production", "football_production")): 1.0,
    ("mlb", ("batter_production", "batter_production")): 1.0,
    ("nhl", ("usage", "usage")): 1.1,
    ("nba", ("possession", "possession")): 1.0,
    ("nba", ("usage", "usage")): 1.2,
    ("wnba", ("possession", "possession")): 1.0,
    ("wnba", ("usage", "usage")): 1.2,
    ("ncaab", ("possession", "possession")): 0.9,
    ("ncaab", ("usage", "usage")): 1.1,
}
_LIVE_PARLAY_PAIR_PENALTY_MULTIPLIER = 1.5
_MIXED_TIMING_PARLAY_PAIR_PENALTY_MULTIPLIER = 1.2
_OPPOSING_DIRECTION_PARLAY_PAIR_PENALTY_MULTIPLIER = 0.65
_DIFFERENT_SUBJECT_PARLAY_PAIR_PENALTY_MULTIPLIER = 0.75
_OPPOSING_TEAM_PARLAY_PAIR_PENALTY_MULTIPLIER = 0.75
_SAME_TEAM_SPORT_MARKET_PAIR_PENALTY_MULTIPLIERS = {
    ("nba", ("assists", "rebounds")): 1.05,
    ("nba", ("points", "rebounds")): 1.15,
    ("nba", ("points", "threes")): 1.1,
    ("wnba", ("assists", "rebounds")): 1.05,
    ("wnba", ("points", "rebounds")): 1.15,
    ("wnba", ("points", "threes")): 1.1,
    ("ncaab", ("assists", "rebounds")): 1.05,
    ("ncaab", ("points", "rebounds")): 1.1,
    ("ncaab", ("points", "threes")): 1.05,
}
_SAME_TEAM_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS = {
    ("ncaaf", ("football_production", "football_production")): 1.05,
    ("nfl", ("football_production", "football_production")): 1.05,
    ("nhl", ("usage", "usage")): 1.05,
    ("mlb", ("batter_production", "batter_production")): 1.05,
}
_OPPOSING_TEAM_SPORT_MARKET_PAIR_PENALTY_MULTIPLIERS = {
    ("nba", ("points", "threes")): 0.65,
    ("wnba", ("points", "threes")): 0.65,
    ("ncaab", ("points", "threes")): 0.7,
}
_OPPOSING_TEAM_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS = {
    ("ncaaf", ("football_production", "football_production")): 0.6,
    ("nfl", ("football_production", "football_production")): 0.6,
    ("nhl", ("usage", "usage")): 0.6,
    ("mlb", ("batter_production", "batter_production")): 0.6,
}
_MARKET_DEFAULT_SPORTS: dict[str, tuple[str, ...]] = {
    "home_runs": ("mlb",),
    "strikeouts": ("mlb",),
    "total_bases": ("mlb",),
    "hits": ("mlb",),
    "rbi": ("mlb",),
}
_ADVANCED_SIGNAL_LABELS = {
    "batter_statcast_bb_mult": "Batter Statcast walk multiplier",
    "batter_statcast_hr_mult": "Batter Statcast home-run multiplier",
    "batter_statcast_inplay_mult": "Batter Statcast in-play multiplier",
    "batter_statcast_k_mult": "Batter Statcast strikeout multiplier",
    "basketball_last5_delta": "Basketball last-five delta",
    "basketball_last10_delta": "Basketball last-10 delta",
    "basketball_last_game_delta": "Basketball last-game delta",
    "basketball_minutes_workload_delta": "Basketball minutes-workload delta",
    "pitcher_statcast_bb_mult": "Pitcher Statcast walk multiplier",
    "pitcher_statcast_hr_mult": "Pitcher Statcast home-run multiplier",
    "pitcher_statcast_inplay_mult": "Pitcher Statcast in-play multiplier",
    "pitcher_statcast_k_mult": "Pitcher Statcast strikeout multiplier",
    "bvp_history_source": "BvP history source",
}
_ADVANCED_SIGNAL_TOKENS = (
    "statcast",
    "advanced",
    "barrel",
    "exit_velocity",
    "launch_angle",
    "hard_hit",
    "pitch_mix",
    "xg",
    "epa",
    "pace",
    "share",
)
_TABLE_REQUEST_TOKENS = ("table", "grid", "matrix", "tabular")
_CHART_REQUEST_TOKENS = ("chart", "graph", "plot", "visual")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _effective_date(selected_date: str | None = None) -> str:
    value = str(selected_date or "").strip()
    return value or central_today_iso()


def _text_contains_keyword(text: str, keyword: str) -> bool:
    normalized_text = str(text or "").lower()
    normalized_keyword = str(keyword or "").strip().lower()
    if not normalized_text or not normalized_keyword:
        return False
    if re.fullmatch(r"[a-z0-9_+-]+", normalized_keyword):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])", normalized_text))
    return normalized_keyword in normalized_text


def _relative_repo_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(_repo_root()).as_posix()
    except Exception:
        return str(path)


def _safe_int(value: Any) -> int | None:
    try:
        text = str(value or "").strip()
        if not text:
            return None
        return int(float(text))
    except Exception:
        return None


def _format_probability_display(value: Any) -> Any:
    percentage = _pct_hint(value)
    if percentage is None:
        return value
    return f"{percentage:.1f}%"


def _american_odds_value(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        number = float(match.group(1))
    except Exception:
        return None
    if number == 0:
        return None
    return number


def _american_to_decimal(value: float | None) -> float | None:
    if value is None:
        return None
    if value > 0:
        return 1.0 + (value / 100.0)
    return 1.0 + (100.0 / abs(value))


def _american_implied_probability(value: float | None) -> float | None:
    if value is None:
        return None
    if value > 0:
        return 100.0 / (value + 100.0)
    return abs(value) / (abs(value) + 100.0)


def odds_to_implied_probability(value: float | None) -> float | None:
    return _american_implied_probability(value)


def _decimal_to_american(value: float | None) -> str | None:
    if value is None or value <= 1.0:
        return None
    profit_multiple = float(value) - 1.0
    if profit_multiple >= 1.0:
        american = int(round(profit_multiple * 100.0))
        return f"+{american}"
    american = int(round(-100.0 / profit_multiple))
    return str(american)


def _normalized_market_text(value: Any) -> str:
    lowered = str(value or "").lower()
    lowered = re.sub(r"([a-z0-9])['’]s\b", r"\1", lowered)
    lowered = re.sub(r"\b3\s*pt\s*m\b", " 3pm ", lowered)
    lowered = re.sub(r"\b3\s*point\s*makes?\b", " 3pm ", lowered)
    lowered = re.sub(r"\bthree\s+point\s+makes?\b", " 3pm ", lowered)
    normalized = re.sub(r"[^a-z0-9]+", " ", lowered).strip()
    return re.sub(r"\s+", " ", normalized)


def _text_has_market_alias(text: str, alias: str) -> bool:
    normalized_text = _normalized_market_text(text)
    normalized_alias = _normalized_market_text(alias)
    if not normalized_text or not normalized_alias:
        return False
    return f" {normalized_alias} " in f" {normalized_text} "


def _fallback_market_key(text: Any) -> str | None:
    normalized = _normalized_market_text(text)
    if not normalized:
        return None
    tokens = [token for token in normalized.split() if token not in _MARKET_FALLBACK_STOPWORDS]
    if not tokens or len(tokens) > 3:
        return None
    return "_".join(tokens)


def _market_key_from_text(text: Any, *, allow_fallback: bool = False) -> str | None:
    normalized = _normalized_market_text(text)
    if not normalized:
        return None
    for key, aliases in _MARKET_FOCUS_ALIASES.items():
        if any(_text_has_market_alias(normalized, alias) for alias in aliases):
            return key
    if allow_fallback:
        return _fallback_market_key(normalized)
    return None


def _market_label(key: str | None) -> str:
    value = str(key or "").strip().lower()
    if not value:
        return "Market"
    label = _MARKET_FOCUS_LABELS.get(value)
    if label:
        return label
    if value.isupper() and len(value) <= 4:
        return value
    return value.replace("_", " ").title()


def _market_focus_labels(keys: list[str] | tuple[str, ...] | None) -> list[str]:
    labels: list[str] = []
    for key in keys or []:
        label = _market_label(str(key).strip().lower())
        if label:
            labels.append(label)
    return labels


def _market_shape_profile(market_key: str | None, *, candidate_type: str, sport_slug: str | None = None) -> dict[str, Any]:
    key = str(market_key or "").strip().lower()
    sport = str(sport_slug or "").strip().lower()
    if candidate_type == "game" or key in _GAME_SIDE_MARKETS:
        return {
            "shape": "game_market",
            "shape_detail": "game_market",
            "margin_weight": 3.5,
            "normalized_margin_weight": 10.0,
            "edge_weight": 0.7,
            "confidence_weight": 0.06,
            "confidence_baseline": 50.0,
            "margin_cap": 5.0,
            "normalized_margin_cap": 0.35,
            "price_edge_weight": 0.7,
            "plus_money_bonus": 0.0,
        }
    if key in _BINARY_CEILING_MARKETS:
        return {
            "shape": "binary_ceiling_prop",
            "shape_detail": "binary_ceiling_prop",
            "margin_weight": 7.5,
            "normalized_margin_weight": 12.0,
            "edge_weight": 0.85,
            "confidence_weight": 0.05,
            "confidence_baseline": 22.0 if key == "home_runs" else 30.0,
            "margin_cap": 1.5,
            "normalized_margin_cap": 1.0,
            "price_edge_weight": 0.5,
            "plus_money_bonus": 2.0,
        }
    if key in _VOLUME_PROP_MARKETS:
        profile = {
            "shape": "volume_prop",
            "shape_detail": "volume_prop",
            "margin_weight": 5.5,
            "normalized_margin_weight": 16.0,
            "edge_weight": 0.55,
            "confidence_weight": 0.07,
            "confidence_baseline": 54.0,
            "margin_cap": 5.0,
            "normalized_margin_cap": 0.5,
            "price_edge_weight": 0.4,
            "plus_money_bonus": 1.25,
        }
        if sport in {"nba", "wnba", "ncaab"}:
            detail_by_sport = {
                "nba": "nba_rebound_environment",
                "wnba": "wnba_possession_pressure",
                "ncaab": "ncaab_tempo_volatility",
            }
            profile["shape_detail"] = detail_by_sport.get(sport, profile["shape_detail"])
        return profile
    if key in _COUNTING_PROP_MARKETS:
        profile = {
            "shape": "counting_prop",
            "shape_detail": "counting_prop",
            "margin_weight": 4.0,
            "normalized_margin_weight": 12.0,
            "edge_weight": 0.45,
            "confidence_weight": 0.08,
            "confidence_baseline": 55.0,
            "margin_cap": 6.0,
            "normalized_margin_cap": 0.35,
            "price_edge_weight": 0.35,
            "plus_money_bonus": 1.0,
        }
        override = _SPORT_MARKET_SHAPE_OVERRIDES.get((sport, key))
        if override:
            profile.update(override)
        return profile
    return {
        "shape": "general_market",
        "shape_detail": "general_market",
        "margin_weight": 4.5,
        "normalized_margin_weight": 14.0,
        "edge_weight": 0.45,
        "confidence_weight": 0.07,
        "confidence_baseline": 54.0 if candidate_type != "game" else 50.0,
        "margin_cap": 5.0,
        "normalized_margin_cap": 0.4,
        "price_edge_weight": 0.35,
        "plus_money_bonus": 1.0 if candidate_type != "game" else 0.0,
    }


def _market_context(candidate: dict[str, Any]) -> dict[str, Any]:
    american_odds = _american_odds_value(candidate.get("odds"))
    decimal_odds = _american_to_decimal(american_odds)
    implied_probability = odds_to_implied_probability(american_odds)
    model_probability_pct = _pct_hint(candidate.get("confidence"))
    price_edge_pct = None
    if implied_probability is not None and model_probability_pct is not None:
        price_edge_pct = model_probability_pct - (implied_probability * 100.0)
    return {
        "american_odds": int(american_odds) if american_odds is not None and float(american_odds).is_integer() else american_odds,
        "decimal_odds": round(decimal_odds, 3) if decimal_odds is not None else None,
        "implied_probability": round(implied_probability * 100.0, 2) if implied_probability is not None else None,
        "model_probability": round(model_probability_pct, 2) if model_probability_pct is not None else None,
        "price_edge_pct": round(price_edge_pct, 2) if price_edge_pct is not None else None,
    }


def _market_score_adjustment(market_context: dict[str, Any]) -> float:
    price_edge_pct = market_context.get("price_edge_pct")
    american_odds = market_context.get("american_odds")
    if price_edge_pct is None:
        return 2.0 if american_odds is not None else 0.0
    adjustment = max(-10.0, min(12.0, float(price_edge_pct) * 0.6))
    if american_odds is not None and float(american_odds) >= 100.0 and float(price_edge_pct) > 0.0:
        adjustment += 1.5
    return adjustment


def _humanize_signal_key(key: str) -> str:
    return _ADVANCED_SIGNAL_LABELS.get(key, key.replace("_", " ").strip().title())


def _item_reason_summary(item: dict[str, Any]) -> str:
    for key in ("basketball_reasons", "top_play_reasons", "reasons"):
        values = item.get(key)
        if not isinstance(values, list):
            continue
        fragments = [str(value).strip() for value in values if str(value).strip()]
        if fragments:
            return "; ".join(fragments[:3])
    return ""


def _item_source_summary(item: dict[str, Any]) -> str:
    for value in (
        item.get("writeup"),
        item.get("basketball_summary"),
        item.get("why_explain"),
        item.get("shape_summary"),
        item.get("summary"),
        item.get("detail"),
        _item_reason_summary(item),
    ):
        text = _safe_text(value, "")
        if text:
            return text
    return ""


def _basketball_summary_signals_from_text(item: dict[str, Any]) -> list[dict[str, Any]]:
    summary_text = " ".join(
        part for part in (
            _safe_text(item.get("basketball_summary"), ""),
            _safe_text(item.get("why_explain"), ""),
            _item_reason_summary(item),
        ) if part
    ).lower()
    line_value = _numeric_hint(item.get("line"))
    signals: list[dict[str, Any]] = []
    if not summary_text:
        return signals

    def append_signal(key: str, value: float) -> None:
        signals.append(
            {
                "key": key,
                "label": _humanize_signal_key(key),
                "value": round(float(value), 3),
            }
        )

    if line_value is not None and line_value > 0:
        patterns = (
            (r"last-five average of (?P<value>\d+(?:\.\d+)?)", "basketball_last5_average", "basketball_last5_delta"),
            (r"last-10 sample(?: is [^.,;]*?)? at (?P<value>\d+(?:\.\d+)?)", "basketball_last10_average", "basketball_last10_delta"),
            (r"last game landed at (?P<value>\d+(?:\.\d+)?)", "basketball_last_game_value", "basketball_last_game_delta"),
        )
        for pattern, raw_key, delta_key in patterns:
            match = re.search(pattern, summary_text)
            if not match:
                continue
            value = float(match.group("value"))
            append_signal(raw_key, value)
            append_signal(delta_key, (value - line_value) / max(line_value, 8.0))

    minutes_match = re.search(
        r"projected minutes \((?P<projected>\d+(?:\.\d+)?)\) (?P<relation>sit above|are lighter than) (?:his|her|their) last-10 workload \((?P<workload>\d+(?:\.\d+)?)\)",
        summary_text,
    )
    if minutes_match:
        projected_minutes = float(minutes_match.group("projected"))
        workload_minutes = float(minutes_match.group("workload"))
        relation = 1.0 if minutes_match.group("relation") == "sit above" else -1.0
        append_signal("basketball_projected_minutes", projected_minutes)
        append_signal("basketball_last10_workload", workload_minutes)
        append_signal(
            "basketball_minutes_workload_delta",
            relation * abs(projected_minutes - workload_minutes) / max(workload_minutes, 12.0),
        )
    return signals


def _basketball_summary_signals_from_fields(item: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = [item]
    for key in ("top_play", "best", "model"):
        nested = item.get(key)
        if isinstance(nested, dict):
            sources.append(nested)

    def first_numeric(*names: str) -> float | None:
        for source in sources:
            for name in names:
                numeric_value = _numeric_hint(source.get(name))
                if numeric_value is not None:
                    return float(numeric_value)
        return None

    def append_signal(target: list[dict[str, Any]], key: str, value: float) -> None:
        target.append(
            {
                "key": key,
                "label": _humanize_signal_key(key),
                "value": round(float(value), 3),
            }
        )

    line_value = first_numeric("line")
    signals: list[dict[str, Any]] = []
    recent_values = (
        (
            first_numeric("basketball_last5_average", "last5_average", "last_5_average", "last5_avg"),
            "basketball_last5_average",
            first_numeric("basketball_last5_delta", "last5_delta_signal", "last5_delta"),
            "basketball_last5_delta",
        ),
        (
            first_numeric("basketball_last10_average", "last10_average", "last_10_average", "last10_avg"),
            "basketball_last10_average",
            first_numeric("basketball_last10_delta", "last10_delta_signal", "last10_delta"),
            "basketball_last10_delta",
        ),
        (
            first_numeric("basketball_last_game_value", "last_game_value", "last_game", "last_game_stat"),
            "basketball_last_game_value",
            first_numeric("basketball_last_game_delta", "last_game_delta_signal", "last_game_delta"),
            "basketball_last_game_delta",
        ),
    )
    for raw_value, raw_key, delta_value, delta_key in recent_values:
        if raw_value is None:
            continue
        append_signal(signals, raw_key, raw_value)
        if delta_value is None and line_value is not None and line_value > 0:
            delta_value = (raw_value - line_value) / max(line_value, 8.0)
        if delta_value is not None:
            append_signal(signals, delta_key, delta_value)

    projected_minutes = first_numeric("basketball_projected_minutes", "projected_minutes")
    workload_minutes = first_numeric("basketball_last10_workload", "last10_workload", "last_10_workload")
    workload_delta = first_numeric(
        "basketball_minutes_workload_delta",
        "workload_delta_signal",
        "minutes_workload_delta",
    )
    if projected_minutes is not None:
        append_signal(signals, "basketball_projected_minutes", projected_minutes)
    if workload_minutes is not None:
        append_signal(signals, "basketball_last10_workload", workload_minutes)
    if workload_delta is None and projected_minutes is not None and workload_minutes is not None:
        workload_delta = (projected_minutes - workload_minutes) / max(workload_minutes, 12.0)
    if workload_delta is not None:
        append_signal(signals, "basketball_minutes_workload_delta", workload_delta)
    return signals


def _advanced_signals_from_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    signals = _basketball_summary_signals_from_fields(item)
    seen_keys = {str(signal.get("key") or "").strip().lower() for signal in signals}
    for raw_key, raw_value in item.items():
        key = str(raw_key or "").strip().lower()
        if not key:
            continue
        if key in seen_keys:
            continue
        if key == "bvp_history_source":
            value = str(raw_value or "").strip()
            if value:
                signals.append({"key": key, "label": _humanize_signal_key(key), "value": value})
                seen_keys.add(key)
            continue
        numeric_value = _numeric_hint(raw_value)
        if numeric_value is None:
            continue
        if key.endswith("_mult") or any(token in key for token in _ADVANCED_SIGNAL_TOKENS):
            signals.append(
                {
                    "key": key,
                    "label": _humanize_signal_key(key),
                    "value": round(float(numeric_value), 3),
                }
            )
            seen_keys.add(key)
    for signal in _basketball_summary_signals_from_text(item):
        key = str(signal.get("key") or "").strip().lower()
        if not key or key in seen_keys:
            continue
        signals.append(signal)
        seen_keys.add(key)
    return signals


def _market_signal_suffixes(candidate: dict[str, Any]) -> tuple[str, ...]:
    market = " ".join(
        [
            _safe_text(candidate.get("market"), "").lower(),
            _safe_text(candidate.get("pick"), "").lower(),
            _safe_text(candidate.get("name"), "").lower(),
        ]
    )
    if any(token in market for token in ("strikeout", "strike out", " ks", "k ")):
        return ("_k_mult",)
    if any(token in market for token in ("home run", " hr", "hr ")):
        return ("_hr_mult",)
    if any(token in market for token in ("walk", " bb", "bb ")):
        return ("_bb_mult",)
    if any(token in market for token in ("hit", "total bases", "tb", "rbi")):
        return ("_inplay_mult", "_hr_mult")
    return ()


def _relevant_advanced_signals(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    signals = candidate.get("advanced_signals") if isinstance(candidate.get("advanced_signals"), list) else []
    suffixes = _market_signal_suffixes(candidate)
    if not suffixes:
        return [signal for signal in signals if isinstance(signal, dict)]
    matched = [
        signal
        for signal in signals
        if isinstance(signal, dict) and any(str(signal.get("key") or "").endswith(suffix) for suffix in suffixes)
    ]
    return matched or [signal for signal in signals if isinstance(signal, dict)]


def _advanced_signal_delta(signal: dict[str, Any]) -> float | None:
    key = _safe_text(signal.get("key"), "").lower()
    value = signal.get("value")
    if not key or not isinstance(value, (int, float)):
        return None
    numeric_value = float(value)
    if key.startswith("basketball_") and key.endswith("_delta"):
        return numeric_value * 4.0
    if key.endswith("_mult"):
        return (numeric_value - 1.0) / 0.12
    if "target_share" in key or key.endswith("_share") or "share_" in key:
        return (numeric_value - 0.18) / 0.08
    if "barrel_rate" in key:
        return (numeric_value - 0.08) / 0.03
    if "hardhit_rate" in key or "hard_hit_rate" in key:
        return (numeric_value - 0.35) / 0.1
    if "hr_per_bip" in key:
        return (numeric_value - 0.06) / 0.025
    if "xwoba" in key:
        return (numeric_value - 0.32) / 0.04
    if 0.0 <= numeric_value <= 1.0:
        return None
    return (numeric_value - 1.0) / 0.12


def _candidate_advanced_signal_score(candidate: dict[str, Any]) -> float:
    normalized_deltas: list[float] = []
    for signal in _relevant_advanced_signals(candidate):
        if not isinstance(signal, dict):
            continue
        delta = _advanced_signal_delta(signal)
        if delta is not None:
            key = _safe_text(signal.get("key"), "").lower()
            if any(token in key for token in ("history", "matchup", "opponent", "allowed", "bvp")):
                delta *= 1.2
            elif any(token in key for token in ("pace", "usage", "shot", "role", "environment", "possession", "pressure")):
                delta *= 1.1
            normalized_deltas.append(delta)
    if not normalized_deltas:
        return 0.0
    direction = -1.0 if "under" in _safe_text(candidate.get("pick"), "").lower() else 1.0
    avg_delta = sum(normalized_deltas) / float(len(normalized_deltas))
    return max(-6.0, min(6.0, avg_delta * 2.5 * direction))


def _candidate_signal_contributions(candidate: dict[str, Any]) -> tuple[dict[str, float], list[dict[str, Any]], list[dict[str, Any]]]:
    relevant_signals = [signal for signal in _relevant_advanced_signals(candidate) if isinstance(signal, dict)]
    if not relevant_signals:
        return {}, [], []

    direction = -1.0 if "under" in _safe_text(candidate.get("pick"), "").lower() else 1.0
    contributions: list[dict[str, Any]] = []
    for signal in relevant_signals:
        delta = _advanced_signal_delta(signal)
        if delta is None:
            continue
        key = _safe_text(signal.get("key"), "signal")
        label = _safe_text(signal.get("label"), key)
        if any(token in key for token in ("history", "matchup", "opponent", "allowed", "bvp")):
            delta *= 1.2
        elif any(token in key for token in ("pace", "usage", "shot", "role", "environment", "possession", "pressure")):
            delta *= 1.1
        weight = _signal_weight(key)
        contributions.append(
            {
                "signal_name": key,
                "label": label,
                "contribution": round(((delta * 2.5 * direction) / float(len(relevant_signals))) * weight, 3),
                "weight": round(weight, 4),
            }
        )

    if not contributions:
        return {}, [], []

    contributions.sort(key=lambda item: (float(item.get("contribution") or 0.0), _safe_text(item.get("signal_name"), "")), reverse=True)
    contributions_map = {str(item.get("signal_name") or "signal"): float(item.get("contribution") or 0.0) for item in contributions}
    top_positive = [dict(item) for item in contributions if float(item.get("contribution") or 0.0) > 0.0][:3]
    top_negative = [dict(item) for item in sorted(contributions, key=lambda item: (float(item.get("contribution") or 0.0), _safe_text(item.get("signal_name"), ""))) if float(item.get("contribution") or 0.0) < 0.0][:2]
    return contributions_map, top_positive, top_negative


def _context_driven_advanced_signals(candidate: dict[str, Any], advanced_context: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not bool(candidate.get("is_live")) or not advanced_context:
        return []

    line_value = _numeric_hint(candidate.get("line"))
    live_projection = _numeric_hint(candidate.get("live_projection"))
    projected_value = _numeric_hint(candidate.get("projected"))
    direction = _candidate_selection_direction(candidate) or 1

    labels = " ".join(
        f"{_safe_text(item.get('label'), '').lower()} {' '.join(str(metric).strip().lower() for metric in (item.get('metrics') or []) if str(metric).strip())}"
        for item in advanced_context
        if isinstance(item, dict)
    )
    signals: list[dict[str, Any]] = []
    if not labels:
        return signals

    def _signal_value_from_margin(reference_value: float | None) -> float | None:
        if reference_value is None or line_value is None:
            return None
        margin = (float(reference_value) - float(line_value)) * float(direction)
        normalized = margin / max(abs(float(line_value)), 1.0)
        return round(max(0.75, min(1.25, 1.0 + normalized)), 3)

    live_margin_value = _signal_value_from_margin(live_projection)
    projection_shift_value = None
    if live_projection is not None and projected_value is not None:
        shift = (float(live_projection) - float(projected_value)) * float(direction)
        normalized_shift = shift / max(abs(float(projected_value)), 1.0)
        projection_shift_value = round(max(0.75, min(1.25, 1.0 + normalized_shift)), 3)

    if any(token in labels for token in ("play-by-play", "pbp", "live recap", "scoring run", "sequence")):
        if live_margin_value is not None:
            signals.append(
                {
                    "key": "live_sequence_pressure_advanced",
                    "label": "Live sequence pressure",
                    "value": live_margin_value,
                }
            )
        if projection_shift_value is not None:
            signals.append(
                {
                    "key": "projection_shift_advanced",
                    "label": "Projection shift",
                    "value": projection_shift_value,
                }
            )

    if any(token in labels for token in ("shift and on-ice sequence recap", "shift deployment", "on-ice tempo", "toi pressure")):
        if live_margin_value is not None:
            signals.append(
                {
                    "key": "shift_pressure_advanced",
                    "label": "Shift pressure",
                    "value": live_margin_value,
                }
            )

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for signal in signals:
        key = _safe_text(signal.get("key"), "")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(signal)
    return unique


def _basketball_source_summary_score(candidate: dict[str, Any]) -> float:
    if _safe_text(candidate.get("sport_slug"), "").lower() not in {"nba", "wnba", "ncaab"}:
        return 0.0
    if _safe_text(candidate.get("candidate_type"), "").lower() != "prop":
        return 0.0
    text = " ".join(
        part for part in (
            _safe_text(candidate.get("writeup"), ""),
            _safe_text(candidate.get("detail"), ""),
            _safe_text(candidate.get("summary"), ""),
        ) if part
    ).lower()
    if not text:
        return 0.0

    direction = -1.0 if "under" in _safe_text(candidate.get("pick"), "").lower() else 1.0
    adjustments: list[float] = []
    matchup_bonus = 0.0
    structured_signals = {
        _safe_text(signal.get("key"), ""): float(signal.get("value") or 0.0)
        for signal in (candidate.get("advanced_signals") or [])
        if isinstance(signal, dict)
        and _safe_text(signal.get("key"), "").startswith("basketball_")
        and isinstance(signal.get("value"), (int, float))
    }
    if structured_signals:
        for key in (
            "basketball_last5_delta",
            "basketball_last10_delta",
            "basketball_last_game_delta",
            "basketball_minutes_workload_delta",
        ):
            if key in structured_signals:
                adjustments.append(direction * structured_signals[key] * 8.0)
        for key, value in structured_signals.items():
            if key.startswith("basketball_") and any(
                token in key
                for token in (
                    "pace",
                    "usage",
                    "shot",
                    "role",
                    "environment",
                    "possession",
                    "pressure",
                    "rotation",
                    "live_shift",
                )
            ):
                adjustments.append(direction * (value - 1.0) * 6.0)

    if direction > 0.0:
        positive_matchup_phrases = {
            "opponent is allowing": 0.55,
            "defense is yielding": 0.55,
            "yielding clean looks": 0.5,
            "efficient pull-up attempts": 0.45,
            "favorable matchup": 0.5,
            "matchup pressure": 0.35,
            "stable volume": 0.35,
            "primary creator workload": 0.35,
            "projected role remains unchanged": 0.25,
            "projected role stays intact": 0.25,
        }
        for phrase, weight in positive_matchup_phrases.items():
            if phrase in text:
                matchup_bonus += weight

    if "not just riding a short heater" in text:
        adjustments.append(0.8 * direction)
    if "supports the lower-volume case" in text or "leans under" in text:
        adjustments.append(-0.8 * direction)

    if not adjustments and matchup_bonus == 0.0:
        return 0.0
    average_adjustment = sum(adjustments) / float(len(adjustments)) if adjustments else 0.0
    return max(-3.0, min(3.0, average_adjustment + matchup_bonus))


def _advanced_signal_text(candidate: dict[str, Any], *, limit: int = 2) -> str:
    fragments: list[str] = []
    for signal in _relevant_advanced_signals(candidate):
        if not isinstance(signal, dict):
            continue
        label = _safe_text(signal.get("label"), "signal")
        value = signal.get("value")
        if isinstance(value, (int, float)):
            fragments.append(f"{label} {float(value):.2f}")
        else:
            text_value = _safe_text(value, "")
            if text_value:
                fragments.append(f"{label} {text_value}")
        if len(fragments) >= limit:
            break
    return "; ".join(fragments)


def _question_targets_mlb_home_runs(question: str) -> bool:
    lowered = str(question or "").lower()
    return any(token in lowered for token in ("home run", "home runs", "homer", "homers", "hr target", "hr targets", "hr matchup", "hr matchups"))


def _question_requests_table(question: str) -> bool:
    lowered = str(question or "").lower()
    return any(token in lowered for token in _TABLE_REQUEST_TOKENS)


def _question_requests_chart(question: str) -> bool:
    lowered = str(question or "").lower()
    return any(token in lowered for token in _CHART_REQUEST_TOKENS)


def _question_requests_explainer(question: str) -> bool:
    lowered = str(question or "").lower()
    return any(token in lowered for token in ("why", "matchup", "matchups", "analysis", "breakdown", "explain"))


def _question_requests_comparison(question: str) -> bool:
    lowered = str(question or "").lower()
    return bool(re.search(r"\b(?:compare|vs\.?|versus)\b", lowered))


def _analysis_focus_from_question(
    question: str,
    requested_sports: list[str] | tuple[str, ...] | None,
    requested_markets: list[str] | tuple[str, ...] | None,
) -> str | None:
    return _runtime_analysis_focus_from_question(
        question,
        requested_sports,
        requested_markets,
        question_targets_mlb_home_runs=_question_targets_mlb_home_runs,
        question_requests_table=_question_requests_table,
        question_requests_chart=_question_requests_chart,
    )


def _analysis_focus_from_resolved_candidates(
    question: str,
    candidates: list[dict[str, Any]],
    preferences: dict[str, Any],
) -> str | None:
    if preferences.get("analysis_focus"):
        return _safe_text(preferences.get("analysis_focus"), "") or None
    if preferences.get("comparison_requested") and len(preferences.get("requested_subjects") or []) >= 2:
        return None
    if not (
        _question_requests_explainer(question)
        or _question_requests_table(question)
        or _question_requests_chart(question)
    ):
        return None

    valid_candidates = [candidate for candidate in candidates if isinstance(candidate, Mapping)]
    if not valid_candidates:
        return None

    sports = {
        _safe_text(candidate.get("sport_slug"), "").lower()
        for candidate in valid_candidates
        if _safe_text(candidate.get("sport_slug"), "").strip()
    }
    candidate_types = {
        _safe_text(candidate.get("candidate_type"), "").lower()
        for candidate in valid_candidates
        if _safe_text(candidate.get("candidate_type"), "").strip()
    }
    requested_markets = [str(item).strip().lower() for item in (preferences.get("requested_markets") or []) if str(item).strip()]

    if len(sports) != 1:
        if sports <= {"nfl", "ncaaf"}:
            return "football_markets"
        return "market_board"

    sport_slug = next(iter(sports))
    if sport_slug == "mlb" and "prop" in candidate_types:
        return "mlb_props"
    if sport_slug == "wnba":
        return "wnba_matchups"
    if sport_slug == "nba":
        return "nba_matchups"
    if sport_slug == "ncaab":
        return "ncaab_matchups"
    if sport_slug in {"nfl", "ncaaf"}:
        return "football_markets"
    if sport_slug == "nhl":
        return "hockey_props"
    if requested_markets or sport_slug:
        return "market_board"
    return None


@lru_cache(maxsize=1)
def _mlb_statcast_feature_payload() -> dict[str, Any]:
    path = _mlb_repo_artifact_path("data", "statcast", "features", "player_features_latest.json")
    try:
        payload = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    try:
        import json

        data = json.loads(payload)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _mlb_statcast_profile_from_ids(batter_id: int | None, pitcher_id: int | None) -> dict[str, Any] | None:
    payload = _mlb_statcast_feature_payload()
    if not payload:
        return None
    batters = payload.get("batters") if isinstance(payload.get("batters"), dict) else {}
    pitchers = payload.get("pitchers") if isinstance(payload.get("pitchers"), dict) else {}
    batter = batters.get(str(int(batter_id))) if batter_id is not None and isinstance(batters.get(str(int(batter_id))), dict) else None
    pitcher = pitchers.get(str(int(pitcher_id))) if pitcher_id is not None and isinstance(pitchers.get(str(int(pitcher_id))), dict) else None
    if not batter and not pitcher:
        return None

    batter_overall = batter.get("overall") if isinstance((batter or {}).get("overall"), dict) else {}
    batter_mult = batter.get("mult_overall") if isinstance((batter or {}).get("mult_overall"), dict) else {}
    pitcher_overall = pitcher.get("overall") if isinstance((pitcher or {}).get("overall"), dict) else {}
    pitcher_mult = pitcher.get("mult_overall") if isinstance((pitcher or {}).get("mult_overall"), dict) else {}
    pitcher_mix = pitcher.get("pitch_mix") if isinstance((pitcher or {}).get("pitch_mix"), dict) else {}
    top_pitch_mix = sorted(
        ((str(key), float(value)) for key, value in pitcher_mix.items() if _numeric_hint(value) is not None),
        key=lambda item: item[1],
        reverse=True,
    )[:3]
    return {
        "batter_id": batter_id,
        "pitcher_id": pitcher_id,
        "batter": {
            "ev_mean": _numeric_hint(batter_overall.get("ev_mean")),
            "la_mean": _numeric_hint(batter_overall.get("la_mean")),
            "barrel_rate": _numeric_hint(batter_overall.get("barrel_rate")),
            "hardhit_rate": _numeric_hint(batter_overall.get("hardhit_rate")),
            "hr_per_bip": _numeric_hint(batter_overall.get("hr_per_bip")),
            "xwoba": _numeric_hint(batter_overall.get("xwoba")),
            "pulled_air_rate": _numeric_hint(batter_overall.get("pulled_air_rate")),
            "hr_mult": _numeric_hint(batter_mult.get("hr")),
            "k_mult": _numeric_hint(batter_mult.get("k")),
            "inplay_mult": _numeric_hint(batter_mult.get("inplay")),
        },
        "pitcher": {
            "ev_mean_allowed": _numeric_hint(pitcher_overall.get("ev_mean")),
            "barrel_rate_allowed": _numeric_hint(pitcher_overall.get("barrel_rate")),
            "hardhit_rate_allowed": _numeric_hint(pitcher_overall.get("hardhit_rate")),
            "hr_per_bip_allowed": _numeric_hint(pitcher_overall.get("hr_per_bip")),
            "xwoba_allowed": _numeric_hint(pitcher_overall.get("xwoba")),
            "hr_mult": _numeric_hint(pitcher_mult.get("hr")),
            "k_mult": _numeric_hint(pitcher_mult.get("k")),
            "inplay_mult": _numeric_hint(pitcher_mult.get("inplay")),
            "top_pitch_mix": [
                {"pitch_type": pitch_type, "share": round(share, 3)}
                for pitch_type, share in top_pitch_mix
            ],
        },
        "generated_at": ((payload.get("meta") or {}).get("generated_at") if isinstance(payload.get("meta"), dict) else None),
    }


def _candidate_mlb_statcast_profile(candidate: dict[str, Any]) -> dict[str, Any] | None:
    if _safe_text(candidate.get("sport_slug"), "").lower() != "mlb":
        return None
    batter_id = _safe_int(candidate.get("batter_id"))
    pitcher_id = _safe_int(candidate.get("opponent_pitcher_id") or candidate.get("pitcher_id"))
    return _mlb_statcast_profile_from_ids(batter_id, pitcher_id)


def _mlb_statcast_profile_text(profile: dict[str, Any] | None) -> str:
    if not isinstance(profile, dict):
        return ""
    batter = profile.get("batter") if isinstance(profile.get("batter"), dict) else {}
    pitcher = profile.get("pitcher") if isinstance(profile.get("pitcher"), dict) else {}
    fragments: list[str] = []
    barrel_rate = batter.get("barrel_rate")
    ev_mean = batter.get("ev_mean")
    hr_per_bip = batter.get("hr_per_bip")
    pitcher_hr_per_bip = pitcher.get("hr_per_bip_allowed")
    if barrel_rate is not None:
        fragments.append(f"barrel {float(barrel_rate) * 100.0:.1f}%")
    if ev_mean is not None:
        fragments.append(f"EV {float(ev_mean):.1f}")
    if hr_per_bip is not None:
        fragments.append(f"batter HR/BIP {float(hr_per_bip) * 100.0:.1f}%")
    if pitcher_hr_per_bip is not None:
        fragments.append(f"pitcher HR/BIP allowed {float(pitcher_hr_per_bip) * 100.0:.1f}%")
    return "; ".join(fragments[:4])


def _mlb_statcast_market_text(profile: dict[str, Any] | None, market_key: str) -> str:
    if not isinstance(profile, dict):
        return ""
    batter = profile.get("batter") if isinstance(profile.get("batter"), dict) else {}
    pitcher = profile.get("pitcher") if isinstance(profile.get("pitcher"), dict) else {}
    normalized_market = _safe_text(market_key, "general_market").lower()
    fragments: list[str] = []
    if normalized_market == "strikeouts":
        if pitcher.get("k_mult") is not None:
            fragments.append(f"pitcher K mult {float(pitcher.get('k_mult')):.2f}")
        if batter.get("k_mult") is not None:
            fragments.append(f"batter K mult {float(batter.get('k_mult')):.2f}")
        pitch_mix = pitcher.get("top_pitch_mix") if isinstance(pitcher.get("top_pitch_mix"), list) else []
        if pitch_mix:
            fragments.append(
                "pitch mix " + ", ".join(
                    f"{_safe_text(item.get('pitch_type'), '?')} {float(item.get('share') or 0.0) * 100.0:.0f}%"
                    for item in pitch_mix[:3]
                    if isinstance(item, dict)
                )
            )
        if pitcher.get("xwoba_allowed") is not None:
            fragments.append(f"pitcher xwOBA allowed {float(pitcher.get('xwoba_allowed')):.3f}")
        return "; ".join(fragments[:4])
    if normalized_market in {"total_bases", "hits", "rbis", "runs_scored"}:
        if batter.get("xwoba") is not None:
            fragments.append(f"batter xwOBA {float(batter.get('xwoba')):.3f}")
        if batter.get("ev_mean") is not None:
            fragments.append(f"EV {float(batter.get('ev_mean')):.1f}")
        if batter.get("hardhit_rate") is not None:
            fragments.append(f"hard-hit {float(batter.get('hardhit_rate')) * 100.0:.1f}%")
        if batter.get("inplay_mult") is not None:
            fragments.append(f"in-play mult {float(batter.get('inplay_mult')):.2f}")
        if pitcher.get("xwoba_allowed") is not None:
            fragments.append(f"pitcher xwOBA allowed {float(pitcher.get('xwoba_allowed')):.3f}")
        return "; ".join(fragments[:5])
    return _mlb_statcast_profile_text(profile)


def _mlb_home_run_analysis_views(candidates: list[dict[str, Any]], preferences: dict[str, Any]) -> dict[str, Any] | None:
    if preferences.get("analysis_focus") != "mlb_home_runs":
        return None
    hr_candidates = [
        candidate
        for candidate in candidates
        if _safe_text(candidate.get("sport_slug"), "").lower() == "mlb"
        and any(
            token in " ".join([_safe_text(candidate.get("market"), "").lower(), _safe_text(candidate.get("name"), "").lower()])
            for token in ("home run", " hr", "hr ")
        )
    ]
    if not hr_candidates:
        return None

    def _signal_value(candidate: dict[str, Any], key: str) -> float | None:
        for signal in candidate.get("advanced_signals") or []:
            if isinstance(signal, dict) and _safe_text(signal.get("key"), "") == key:
                value = signal.get("value")
                if isinstance(value, (int, float)):
                    return round(float(value), 3)
        return None

    top_rows = hr_candidates[: min(int(preferences.get("limit") or 5), 10)]
    table_rows: list[dict[str, Any]] = []
    chart_rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(top_rows, start=1):
        batter_hr_mult = _signal_value(candidate, "batter_statcast_hr_mult")
        pitcher_hr_mult = _signal_value(candidate, "pitcher_statcast_hr_mult")
        statcast_profile = candidate.get("mlb_statcast_profile") if isinstance(candidate.get("mlb_statcast_profile"), dict) else {}
        batter_profile = statcast_profile.get("batter") if isinstance(statcast_profile.get("batter"), dict) else {}
        pitcher_profile = statcast_profile.get("pitcher") if isinstance(statcast_profile.get("pitcher"), dict) else {}
        table_rows.append(
            {
                "rank": index,
                "player": _safe_text(candidate.get("name"), "Play"),
                "matchup": _safe_text(candidate.get("matchup"), "-"),
                "pick": _safe_text(candidate.get("pick"), "-"),
                "odds": _safe_text(candidate.get("odds"), "-"),
                "confidence": _safe_text(candidate.get("confidence"), "-"),
                "edge": _safe_text(candidate.get("edge"), "-"),
                "score": round(float(candidate.get("score") or 0.0), 2),
                "advanced_signal_score": round(float(candidate.get("advanced_signal_score") or 0.0), 2),
                "batter_hr_mult": batter_hr_mult,
                "pitcher_hr_mult": pitcher_hr_mult,
                "barrel_rate": round(float(batter_profile.get("barrel_rate") or 0.0) * 100.0, 1) if batter_profile.get("barrel_rate") is not None else None,
                "ev_mean": round(float(batter_profile.get("ev_mean") or 0.0), 1) if batter_profile.get("ev_mean") is not None else None,
                "batter_hr_per_bip": round(float(batter_profile.get("hr_per_bip") or 0.0) * 100.0, 1) if batter_profile.get("hr_per_bip") is not None else None,
                "pitcher_hr_per_bip_allowed": round(float(pitcher_profile.get("hr_per_bip_allowed") or 0.0) * 100.0, 1) if pitcher_profile.get("hr_per_bip_allowed") is not None else None,
                "why": _mlb_statcast_profile_text(statcast_profile) or _advanced_signal_text(candidate, limit=3) or _safe_text(candidate.get("writeup"), "-"),
            }
        )
        chart_rows.append(
            {
                "label": _safe_text(candidate.get("name"), "Play"),
                "score": round(float(candidate.get("score") or 0.0), 2),
                "advanced_signal_score": round(float(candidate.get("advanced_signal_score") or 0.0), 2),
                "confidence": _pct_hint(candidate.get("confidence")),
                "batter_hr_mult": batter_hr_mult,
                "pitcher_hr_mult": pitcher_hr_mult,
                "barrel_rate": round(float(batter_profile.get("barrel_rate") or 0.0) * 100.0, 1) if batter_profile.get("barrel_rate") is not None else None,
                "ev_mean": round(float(batter_profile.get("ev_mean") or 0.0), 1) if batter_profile.get("ev_mean") is not None else None,
            }
        )

    return {
        "focus": "mlb_home_runs",
        "title": "Top MLB home run targets",
        "table": {
            "title": "Top 10 likely HR targets",
            "columns": [
                "rank",
                "player",
                "matchup",
                "pick",
                "odds",
                "confidence",
                "edge",
                "score",
                "advanced_signal_score",
                "batter_hr_mult",
                "pitcher_hr_mult",
                "barrel_rate",
                "ev_mean",
                "batter_hr_per_bip",
                "pitcher_hr_per_bip_allowed",
                "why",
            ],
            "rows": table_rows,
        },
        "chart": {
            "title": "HR target score grid",
            "type": "bar",
            "x_key": "label",
            "series": ["score", "advanced_signal_score", "confidence", "batter_hr_mult", "pitcher_hr_mult", "barrel_rate", "ev_mean"],
            "rows": chart_rows,
        },
    }


def _candidate_analysis_row(candidate: dict[str, Any], index: int) -> dict[str, Any]:
    market_context = candidate.get("market_context") if isinstance(candidate.get("market_context"), dict) else {}
    market_fit = candidate.get("market_fit") if isinstance(candidate.get("market_fit"), dict) else {}
    if "historical_context" in candidate:
        historical_context = candidate.get("historical_context") if isinstance(candidate.get("historical_context"), dict) else {"roi_segment": None, "sample_size": None}
        roi_segment_value = historical_context.get("roi_segment")
        sample_size_value = historical_context.get("sample_size")
    else:
        historical_profile = candidate.get("historical_profile") if isinstance(candidate.get("historical_profile"), dict) else {}
        market_profile = historical_profile.get("market") if isinstance(historical_profile.get("market"), dict) else {}
        sport_profile = historical_profile.get("sport") if isinstance(historical_profile.get("sport"), dict) else {}
        historical_source = market_profile if int(market_profile.get("sample_size") or 0) > 0 else sport_profile
        historical_metrics = historical_source.get("metrics") if isinstance(historical_source.get("metrics"), dict) else {}
        roi_segment = historical_metrics.get("roi")
        sample_size = historical_source.get("sample_size") or historical_metrics.get("sample_size") or historical_metrics.get("settled_count")
        try:
            roi_segment_value = float(roi_segment) if roi_segment is not None else None
        except Exception:
            roi_segment_value = None
        try:
            sample_size_value = int(sample_size) if sample_size is not None else None
        except Exception:
            sample_size_value = None
    model_probability = _numeric_hint(candidate.get("model_probability") or market_context.get("model_probability") or candidate.get("confidence"))
    market_probability = _numeric_hint(candidate.get("market_probability") or market_context.get("implied_probability") or candidate.get("implied_probability"))
    edge_value = candidate.get("edge_pct")
    if edge_value is None:
        raw_edge = candidate.get("edge")
        if isinstance(raw_edge, (int, float)):
            edge_value = float(raw_edge) * 100.0
    expected_value = candidate.get("expected_value")
    try:
        expected_value = float(expected_value) if expected_value is not None else None
    except Exception:
        expected_value = None
    why = (
        _safe_text(market_fit.get("market_fit_note"), "")
        or _advanced_signal_text(candidate, limit=3)
        or _safe_text(candidate.get("writeup"), "")
        or _safe_text(candidate.get("detail"), "")
        or _safe_text(candidate.get("summary"), "")
    )
    reasoning: list[str] = []
    if why:
        reasoning.append(why)
    if model_probability is not None and market_probability is not None:
        if isinstance(edge_value, (int, float)):
            reasoning.append(f"Model {model_probability:.3f} vs market {market_probability:.3f} ({float(edge_value):+.2f} pts)")
        else:
            reasoning.append(f"Model {model_probability:.3f} vs market {market_probability:.3f}")
    if roi_segment_value is not None and sample_size_value is not None:
        reasoning.append(f"Historical ROI {roi_segment_value:+.3f} across {sample_size_value} settled bets")
    elif sample_size_value is not None:
        reasoning.append(f"Historical sample size {sample_size_value} settled bets")
    return {
        "rank": index,
        "label": _safe_text(candidate.get("name"), "Play"),
        "sport": _safe_text(candidate.get("sport"), "Sport"),
        "matchup": _safe_text(candidate.get("matchup"), "-"),
        "market": _safe_text(candidate.get("market"), "Market"),
        "market_label": _safe_text(market_fit.get("market_label"), "Market"),
        "market_shape": _safe_text(market_fit.get("market_shape"), "general_market"),
        "pick": _safe_text(candidate.get("pick"), "-"),
        "line": _safe_text(candidate.get("line"), "-"),
        "projected": _safe_text(candidate.get("projected"), "-"),
        "live_projection": _safe_text(candidate.get("live_projection"), "-"),
        "actual": _safe_text(candidate.get("actual"), "-"),
        "odds": _safe_text(candidate.get("odds"), "-"),
        "confidence": _safe_text(candidate.get("confidence"), "-"),
        "edge": _safe_text(candidate.get("edge"), "-"),
        "score": round(float(candidate.get("score") or 0.0), 2),
        "market_fit_score": round(float(market_fit.get("market_fit_score") or 0.0), 2),
        "price_edge_pct": market_context.get("price_edge_pct"),
        "implied_probability": market_context.get("implied_probability"),
        "expected_value": expected_value,
        "edge_pct": round(float(edge_value), 2) if isinstance(edge_value, (int, float)) else None,
        "model_probability": model_probability,
        "market_probability": market_probability,
        "historical_context": {
            "roi_segment": roi_segment_value,
            "sample_size": sample_size_value,
        },
        "reasoning": reasoning[:3],
        "why": why or "Local board and model context support this angle.",
    }


def _analysis_candidate_rows(
    candidates: list[dict[str, Any]],
    *,
    sports: set[str],
    preferences: dict[str, Any],
) -> list[dict[str, Any]]:
    requested_markets = {str(item).strip().lower() for item in (preferences.get("requested_markets") or []) if str(item).strip()}
    filtered = [candidate for candidate in candidates if _safe_text(candidate.get("sport_slug"), "").lower() in sports]
    if requested_markets:
        filtered = [candidate for candidate in filtered if _candidate_market_focuses(candidate) & requested_markets]
    top_rows = filtered[: min(int(preferences.get("limit") or 5), 10)]
    return [_candidate_analysis_row(candidate, index) for index, candidate in enumerate(top_rows, start=1)]


def _basketball_matchup_analysis_views(candidates: list[dict[str, Any]], preferences: dict[str, Any]) -> dict[str, Any] | None:
    if preferences.get("analysis_focus") != "basketball_matchups":
        return None
    table_rows = _analysis_candidate_rows(candidates, sports={"nba", "wnba", "ncaab"}, preferences=preferences)
    if not table_rows:
        return None
    return {
        "focus": "basketball_matchups",
        "title": "Top basketball matchup targets",
        "table": {
            "title": "Top matchup-backed basketball targets",
            "columns": ["rank", "label", "sport", "matchup", "market", "pick", "line", "projected", "live_projection", "odds", "expected_value", "edge_pct", "confidence", "model_probability", "market_probability", "historical_context", "reasoning", "score", "market_fit_score", "why"],
            "rows": table_rows,
        },
        "chart": {
            "title": "Basketball matchup score grid",
            "type": "bar",
            "x_key": "label",
            "series": ["score", "market_fit_score", "price_edge_pct"],
            "rows": table_rows,
        },
    }


def _football_market_analysis_views(candidates: list[dict[str, Any]], preferences: dict[str, Any]) -> dict[str, Any] | None:
    if preferences.get("analysis_focus") != "football_markets":
        return None
    table_rows = _analysis_candidate_rows(candidates, sports={"nfl", "ncaaf"}, preferences=preferences)
    if not table_rows:
        return None
    return {
        "focus": "football_markets",
        "title": "Top football market targets",
        "table": {
            "title": "Top football market targets",
            "columns": ["rank", "label", "sport", "matchup", "market_label", "pick", "line", "projected", "odds", "expected_value", "edge_pct", "confidence", "model_probability", "market_probability", "historical_context", "reasoning", "score", "market_fit_score", "implied_probability", "why"],
            "rows": table_rows,
        },
        "chart": {
            "title": "Football market score grid",
            "type": "bar",
            "x_key": "label",
            "series": ["score", "market_fit_score", "implied_probability"],
            "rows": table_rows,
        },
    }


def _hockey_prop_analysis_views(candidates: list[dict[str, Any]], preferences: dict[str, Any]) -> dict[str, Any] | None:
    if preferences.get("analysis_focus") != "hockey_props":
        return None
    table_rows = _analysis_candidate_rows(candidates, sports={"nhl"}, preferences=preferences)
    if not table_rows:
        return None
    return {
        "focus": "hockey_props",
        "title": "Top hockey prop targets",
        "table": {
            "title": "Top hockey prop targets",
            "columns": ["rank", "label", "matchup", "market_label", "pick", "line", "live_projection", "odds", "expected_value", "edge_pct", "confidence", "model_probability", "market_probability", "historical_context", "reasoning", "score", "market_fit_score", "why"],
            "rows": table_rows,
        },
        "chart": {
            "title": "Hockey prop score grid",
            "type": "bar",
            "x_key": "label",
            "series": ["score", "market_fit_score", "price_edge_pct"],
            "rows": table_rows,
        },
    }


def _comparison_analysis_views(candidates: list[dict[str, Any]], preferences: dict[str, Any]) -> dict[str, Any] | None:
    requested_subjects = [str(item).strip().lower() for item in (preferences.get("requested_subjects") or []) if str(item).strip()]
    if not preferences.get("comparison_requested") or len(requested_subjects) < 2:
        return None

    table_rows: list[dict[str, Any]] = []
    chart_rows: list[dict[str, Any]] = []
    for index, subject_key in enumerate(requested_subjects[:6], start=1):
        candidate = next((item for item in candidates if _candidate_subject_key(item) == subject_key), None)
        if not isinstance(candidate, Mapping):
            continue
        row = _candidate_analysis_row(candidate, index)
        row["subject"] = " ".join(part.capitalize() for part in subject_key.split())
        table_rows.append(row)
        chart_rows.append(
            {
                "label": row["subject"],
                "score": row.get("score"),
                "market_fit_score": row.get("market_fit_score"),
                "price_edge_pct": row.get("price_edge_pct"),
            }
        )
    if len(table_rows) < 2:
        return None

    return {
        "focus": "subject_comparison",
        "title": "Target comparison",
        "table": {
            "title": "Side-by-side comparison",
            "columns": ["rank", "subject", "sport", "matchup", "market", "pick", "line", "odds", "expected_value", "edge_pct", "confidence", "model_probability", "market_probability", "historical_context", "reasoning", "score", "market_fit_score", "why"],
            "rows": table_rows,
        },
        "chart": {
            "title": "Comparison score grid",
            "type": "bar",
            "x_key": "label",
            "series": ["score", "market_fit_score", "price_edge_pct"],
            "rows": chart_rows,
        },
    }


def _analysis_views_for_query(candidates: list[dict[str, Any]], preferences: dict[str, Any]) -> dict[str, Any] | None:
    comparison_view = _comparison_analysis_views(candidates, preferences)
    if comparison_view is not None:
        return comparison_view
    return _runtime_build_analysis_views(
        candidates,
        preferences,
        build_mlb_home_run_analysis_views=_mlb_home_run_analysis_views,
        mlb_statcast_market_text=_mlb_statcast_market_text,
        safe_text=_safe_text,
        candidate_market_focuses=_candidate_market_focuses,
        advanced_signal_text=_advanced_signal_text,
    )


def _extract_american_odds_range(text: str, *, require_parlay_context: bool = False) -> tuple[int | None, int | None]:
    patterns = [
        r"between\s*([+-]\d+)\s*(?:and|to|through)\s*([+-]\d+)",
        r"([+-]\d+)\s*(?:to|through|-)\s*([+-]\d+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            span_start = max(0, match.start() - 32)
            span_end = min(len(text), match.end() + 32)
            window = text[span_start:span_end]
            if require_parlay_context and not any(token in window for token in ("parlay", "combined", "same ticket")):
                continue
            try:
                first = int(match.group(1))
                second = int(match.group(2))
            except Exception:
                continue
            return (min(first, second), max(first, second))
    return (None, None)


def _american_odds_match(american_odds: float | int | None, preferences: dict[str, Any], *, parlay: bool = False) -> bool:
    if american_odds is None:
        return not any(
            preferences.get(key) is not None or preferences.get(key) is True
            for key in (
                "plus_money_only",
                "candidate_odds_min",
                "candidate_odds_max",
                "favorite_floor",
                "parlay_odds_min",
                "parlay_odds_max",
            )
        )

    value = float(american_odds)
    if parlay:
        parlay_min = preferences.get("parlay_odds_min")
        parlay_max = preferences.get("parlay_odds_max")
        if parlay_min is not None and value < float(parlay_min):
            return False
        if parlay_max is not None and value > float(parlay_max):
            return False
        return True

    if preferences.get("plus_money_only") and value < 100.0:
        return False
    favorite_floor = preferences.get("favorite_floor")
    if favorite_floor is not None and value < float(favorite_floor):
        return False
    candidate_min = preferences.get("candidate_odds_min")
    if candidate_min is not None and value < float(candidate_min):
        return False
    candidate_max = preferences.get("candidate_odds_max")
    if candidate_max is not None and value > float(candidate_max):
        return False
    return True


def _parse_parlay_leg_token(value: str | None) -> int | None:
    token = str(value or "").strip().lower()
    count = _PARLAY_LEG_WORDS.get(token)
    if count is None:
        return None
    return max(2, min(5, int(count)))


def _extract_parlay_leg_preferences(text: str) -> tuple[int | None, int | None]:
    lowered = str(text or "").lower()
    range_match = re.search(
        r"\b(?P<first>two|three|four|five|[2-5])\s*(?:-|to|through|and)\s*(?P<second>two|three|four|five|[2-5])\s*[-\s]*(?:leg|legs|legger)\b",
        lowered,
    )
    if range_match:
        first = _parse_parlay_leg_token(range_match.group("first"))
        second = _parse_parlay_leg_token(range_match.group("second"))
        if first is not None and second is not None:
            return (min(first, second), max(first, second))

    exact_match = re.search(r"\b(?P<count>two|three|four|five|[2-5])\s*[-\s]?(?:leg|legs|legger)\b", lowered)
    if exact_match:
        count = _parse_parlay_leg_token(exact_match.group("count"))
        if count is not None:
            return (count, count)
    return (None, None)


def _extract_round_robin_unit(text: str) -> int | None:
    lowered = str(text or "").lower()
    match = re.search(r"\b(?P<count>[2-4])s\s+round robin\b", lowered)
    if not match:
        match = re.search(r"\bround robin(?:\s+by\s+|\s+using\s+)(?P<count>[2-4])s\b", lowered)
    if not match:
        return None
    return max(2, min(4, int(match.group("count"))))


def _extract_bankroll_amount(text: str) -> int | None:
    lowered = str(text or "").lower()
    match = re.search(r"\b(?:bankroll|roll|budget)\s*(?:of|is)?\s*\$\s*(?P<amount>\d{2,6})\b", lowered)
    if not match:
        match = re.search(r"\$\s*(?P<amount>\d{2,6})\s*(?:bankroll|roll|budget)\b", lowered)
    if not match:
        return None
    return int(match.group("amount"))


def _extract_max_exposure_preferences(text: str) -> tuple[int | None, int | None]:
    lowered = str(text or "").lower()
    pct_match = re.search(r"\b(?:max(?:imum)?|cap|limit)\s*(?:exposure|risk)\s*(?:of|at)?\s*(?P<pct>\d{1,2})\s*%", lowered)
    if not pct_match:
        pct_match = re.search(r"\b(?P<pct>\d{1,2})\s*%\s*(?:max(?:imum)?\s*)?(?:exposure|risk)\b", lowered)
    amount_match = re.search(r"\b(?:max(?:imum)?|cap|limit)\s*(?:exposure|risk)\s*(?:of|at)?\s*\$\s*(?P<amount>\d{1,6})", lowered)
    if not amount_match:
        amount_match = re.search(r"\$\s*(?P<amount>\d{1,6})\s*(?:max(?:imum)?\s*)?(?:exposure|risk)\b", lowered)
    max_pct = int(pct_match.group("pct")) if pct_match else None
    max_amount = int(amount_match.group("amount")) if amount_match else None
    return (max_pct, max_amount)


def _extract_market_focuses(text: str) -> list[str]:
    matches: list[str] = []
    for key, aliases in _MARKET_FOCUS_ALIASES.items():
        if any(_text_has_market_alias(text, alias) for alias in aliases):
            matches.append(key)
    if "total_bases" in matches and "total" in matches:
        matches = [key for key in matches if key != "total"]
    return matches


def _extract_parlay_structure_preferences(text: str) -> dict[str, Any]:
    lowered = str(text or "").lower()
    parlay_type = "standard"
    if "round robin" in lowered:
        parlay_type = "round_robin"
    elif re.search(r"\b(?:same game|same-game|sgp)\b", lowered):
        parlay_type = "same_game"

    cross_sport_required = bool(re.search(r"\b(?:cross[-\s]?sport|multi[-\s]?sport|across sports?)\b", lowered))

    has_conservative_risk = any(token in lowered for token in _CONSERVATIVE_RISK_TOKENS)
    has_aggressive_risk = any(token in lowered for token in _AGGRESSIVE_RISK_TOKENS)

    risk_profile = "balanced"
    if has_conservative_risk and has_aggressive_risk and _question_requests_comparison(lowered):
        risk_profile = "balanced"
    elif has_conservative_risk:
        risk_profile = "conservative"
    elif has_aggressive_risk:
        risk_profile = "aggressive"

    correlation_tolerance = "medium"
    correlation_explicit = False
    if any(token in lowered for token in _LOW_CORRELATION_TOKENS):
        correlation_tolerance = "low"
        correlation_explicit = True
    elif any(token in lowered for token in _MEDIUM_CORRELATION_TOKENS):
        correlation_tolerance = "medium"
        correlation_explicit = True
    elif any(token in lowered for token in _HIGH_CORRELATION_TOKENS) or parlay_type == "same_game":
        correlation_tolerance = "high"
        correlation_explicit = True

    round_robin_unit = _extract_round_robin_unit(lowered) if parlay_type == "round_robin" else None
    if parlay_type == "round_robin" and round_robin_unit is None:
        round_robin_unit = 2
    bankroll_amount = _extract_bankroll_amount(lowered)
    max_exposure_pct, max_exposure_amount = _extract_max_exposure_preferences(lowered)

    return {
        "parlay_type": parlay_type,
        "cross_sport_required": cross_sport_required,
        "risk_profile": risk_profile,
        "correlation_tolerance": correlation_tolerance,
        "correlation_explicit": correlation_explicit,
        "round_robin_unit": round_robin_unit,
        "bankroll_amount": bankroll_amount,
        "max_exposure_pct": max_exposure_pct,
        "max_exposure_amount": max_exposure_amount,
    }


def _parlay_request_summary(preferences: dict[str, Any]) -> dict[str, Any]:
    requested_sports = [str(slug).upper() for slug in (preferences.get("requested_sports") or []) if str(slug).strip()]
    requested_markets = _market_focus_labels(preferences.get("requested_markets") or [])
    requested_subjects = [
        " ".join(part.capitalize() for part in str(subject).split())
        for subject in (preferences.get("requested_subjects") or [])
        if str(subject).strip()
    ]
    requested_date = _safe_text(preferences.get("requested_date"), "")
    board_scope: list[str] = []
    if preferences.get("include_props"):
        board_scope.append("Props")
    if preferences.get("include_games"):
        board_scope.append("Games")

    timing = "Live + pregame"
    if preferences.get("live_only"):
        timing = "Live only"
    elif preferences.get("pregame_only"):
        timing = "Pregame only"

    leg_min = preferences.get("parlay_leg_min")
    leg_max = preferences.get("parlay_leg_max")
    leg_window = None
    if leg_min is not None and leg_max is not None:
        leg_window = f"{leg_min} legs" if int(leg_min) == int(leg_max) else f"{leg_min}-{leg_max} legs"

    parlay_type = _safe_text(preferences.get("parlay_type"), "standard")
    type_label = {
        "standard": "Standard parlay",
        "same_game": "Same-game parlay",
        "round_robin": "Round robin",
    }.get(parlay_type, "Standard parlay")

    chips = [type_label, timing]
    if board_scope:
        chips.extend(board_scope)
    limit_value = int(preferences.get("limit") or 0)
    if limit_value > 0:
        chips.append(f"Top {limit_value}")
    if requested_sports:
        chips.append("/".join(requested_sports))
    chips.extend(requested_markets)
    chips.extend(requested_subjects[:3])
    if requested_date:
        chips.append(requested_date)
    if leg_window:
        chips.append(leg_window)
    if preferences.get("cross_sport_required"):
        chips.append("Cross-sport")
    chips.append(f"{_safe_text(preferences.get('risk_profile'), 'balanced').capitalize()} risk")
    chips.append(f"{_safe_text(preferences.get('correlation_tolerance'), 'medium').capitalize()} correlation")
    if preferences.get("parlay_type") == "round_robin":
        unit = preferences.get("round_robin_unit") or 2
        chips.append(f"{unit}-leg tickets")
    if preferences.get("bankroll_amount") is not None:
        chips.append(f"${int(preferences.get('bankroll_amount'))} bankroll")
    if preferences.get("max_exposure_pct") is not None:
        chips.append(f"Max {int(preferences.get('max_exposure_pct'))}% exposure")
    if preferences.get("max_exposure_amount") is not None:
        chips.append(f"Max ${int(preferences.get('max_exposure_amount'))} exposure")

    return {
        "intent": _safe_text(preferences.get("intent"), "best_bets"),
        "sports": requested_sports,
        "requested_markets": requested_markets,
        "requested_subjects": requested_subjects,
        "requested_date": requested_date or None,
        "timing": timing,
        "board_scope": board_scope,
        "parlay_type": parlay_type,
        "leg_window": leg_window,
        "cross_sport_required": bool(preferences.get("cross_sport_required")),
        "risk_profile": _safe_text(preferences.get("risk_profile"), "balanced"),
        "correlation_tolerance": _safe_text(preferences.get("correlation_tolerance"), "medium"),
        "round_robin_unit": preferences.get("round_robin_unit"),
        "bankroll_amount": preferences.get("bankroll_amount"),
        "max_exposure_pct": preferences.get("max_exposure_pct"),
        "max_exposure_amount": preferences.get("max_exposure_amount"),
        "chips": chips,
    }


@lru_cache(maxsize=1)
def _tracked_repo_files() -> set[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(_repo_root()), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return set()
    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}


def _query_preferences(
    question: str,
    *,
    mode: str | None = None,
    sport: str | None = None,
    game_state: str | None = None,
    limit: int | None = None,
    timing: str | None = None,
    include_props: bool | None = None,
    include_games: bool | None = None,
    policy: str | None = None,
) -> dict[str, Any]:
    lowered = str(question or "").lower()
    explicit_mode = str(mode or "").strip().lower()
    explicit_sport = str(sport or "").strip().lower()
    explicit_game_state = str(game_state or "").strip().lower()
    if explicit_sport in {"all", "any", "everything", "*"}:
        explicit_sport = ""
    if explicit_game_state in {"all", "any", "everything", "*"}:
        explicit_game_state = ""
    explicit_timing = str(timing or "").strip().lower()
    explicit_policy = str(policy or "").strip().lower() or None
    explicit_include_props = include_props
    explicit_include_games = include_games
    parlay_structure = _extract_parlay_structure_preferences(lowered)

    requested_sports = set()
    if explicit_sport:
        requested_sports.add(explicit_sport)
    for slug, keywords in _SPORT_KEYWORDS.items():
        if any(_text_contains_keyword(lowered, keyword) for keyword in keywords):
            requested_sports.add(slug)

    requested_markets = _extract_market_focuses(lowered)
    requested_market_set = set(requested_markets)
    if not requested_sports:
        for market_key in requested_markets:
            for slug in _MARKET_DEFAULT_SPORTS.get(market_key, ()): 
                requested_sports.add(slug)

    intent = "best_bets"
    if explicit_mode in {"parlay", "parlays"} or "parlay" in lowered or parlay_structure.get("parlay_type") != "standard":
        intent = "parlay"
    elif explicit_mode in {"live", "live_bets"} or "live bet" in lowered or "in-game" in lowered or "live board" in lowered:
        intent = "live_bets"
    elif explicit_mode in {"pregame", "pregame_bets"} or "pregame" in lowered:
        intent = "pregame_bets"

    live_requested = bool(re.search(r"\b(?:live|in-game|in game|live board)\b", lowered)) or explicit_mode in {"live", "live_bets"}
    pregame_requested = "pregame" in lowered or explicit_mode in {"pregame", "pregame_bets"}
    if explicit_game_state == "live":
        live_requested = True
        pregame_requested = False
    elif explicit_game_state == "pregame":
        pregame_requested = True
        live_requested = False
    live_only = intent == "live_bets" or (live_requested and not pregame_requested)
    pregame_only = intent == "pregame_bets" or (pregame_requested and not live_requested)
    if "live and pregame" in lowered or "pregame and live" in lowered:
        live_only = False
        pregame_only = False
    if explicit_timing == "live":
        if intent != "parlay":
            intent = "live_bets"
        live_only = True
        pregame_only = False
    elif explicit_timing == "pregame":
        if intent != "parlay":
            intent = "pregame_bets"
        live_only = False
        pregame_only = True
    elif explicit_timing in {"all", "both", "mixed"}:
        live_only = False
        pregame_only = False

    prop_market_requested = bool(requested_market_set - _GAME_SIDE_MARKETS)
    game_market_requested = bool(requested_market_set & _GAME_SIDE_MARKETS)
    include_props = any(keyword in lowered for keyword in _PROP_MARKET_KEYWORDS) or prop_market_requested
    include_games = any(keyword in lowered for keyword in _GAME_MARKET_KEYWORDS)
    if prop_market_requested and not game_market_requested:
        include_games = False
    if explicit_mode in {"game", "games"}:
        include_games = True
        include_props = False
    if explicit_mode in {"prop", "props"}:
        include_props = True
        include_games = False
    if explicit_include_props is not None:
        include_props = bool(explicit_include_props)
    if explicit_include_games is not None:
        include_games = bool(explicit_include_games)
    if not include_props and not include_games:
        include_props = True
        include_games = True

    requested_limit = int(limit or 0) if str(limit or "").strip() else 0
    if requested_limit <= 0:
        match = re.search(r"\b(?:top|best)\s+(\d+)\b", lowered)
        if match:
            requested_limit = int(match.group(1))
    if requested_limit <= 0:
        # 2026-08-01: was 5. The main board grid (board_contract.cards) was
        # never actually bound by this -- it renders the full ranked pool
        # unbounded (rank_global_recommendations(..., limit=None)) -- but
        # any caller that omits an explicit limit (Ask the Syndicate, direct
        # API callers) fell through to this default for the separate
        # "recommendations"/"top_opportunities" list, which is small enough
        # to silently make a single dominant sport (e.g. MLB once its props
        # are flowing) look like the entire board. Raised to reflect a
        # broader default slice of the real pool rather than a top-5 sliver.
        requested_limit = 300

    plus_money_only = any(token in lowered for token in ("plus money", "plus-money", "plus odds"))
    favorite_floor = None
    favorite_cap_match = re.search(r"(?:under|below|up to|max(?:imum)?|no worse than|better than)\s*(-\d+)", lowered)
    if favorite_cap_match:
        favorite_floor = int(favorite_cap_match.group(1))

    candidate_odds_min = None
    candidate_odds_max = None
    min_match = re.search(r"(?:over|above|at least|min(?:imum)?)\s*(\+\d+)", lowered)
    if min_match:
        candidate_odds_min = int(min_match.group(1))
    max_match = re.search(r"(?:under|below|up to|max(?:imum)?)\s*(\+\d+)", lowered)
    if max_match:
        candidate_odds_max = int(max_match.group(1))

    parlay_odds_min, parlay_odds_max = _extract_american_odds_range(lowered, require_parlay_context=True)
    parlay_leg_min, parlay_leg_max = _extract_parlay_leg_preferences(lowered)
    requested_date = _question_requested_date(question)
    analysis_focus = _analysis_focus_from_question(question, sorted(requested_sports), requested_markets)
    comparison_requested = _question_requests_comparison(question)
    wants_table = _question_requests_table(question) or analysis_focus is not None
    wants_chart = _question_requests_chart(question) or analysis_focus is not None

    return {
        "intent": intent,
        "requested_sports": sorted(requested_sports),
        "requested_markets": requested_markets,
        "game_state": explicit_game_state or None,
        "include_props": include_props,
        "include_games": include_games,
        "policy": explicit_policy,
        "live_only": live_only,
        "pregame_only": pregame_only,
        "plus_money_only": plus_money_only,
        "favorite_floor": favorite_floor,
        "candidate_odds_min": candidate_odds_min,
        "candidate_odds_max": candidate_odds_max,
        "parlay_odds_min": parlay_odds_min,
        "parlay_odds_max": parlay_odds_max,
        "parlay_leg_min": parlay_leg_min,
        "parlay_leg_max": parlay_leg_max,
        "parlay_type": parlay_structure["parlay_type"],
        "cross_sport_required": parlay_structure["cross_sport_required"],
        "risk_profile": parlay_structure["risk_profile"],
        "correlation_tolerance": parlay_structure["correlation_tolerance"],
        "correlation_explicit": parlay_structure["correlation_explicit"],
        "round_robin_unit": parlay_structure["round_robin_unit"],
        "bankroll_amount": parlay_structure["bankroll_amount"],
        "max_exposure_pct": parlay_structure["max_exposure_pct"],
        "max_exposure_amount": parlay_structure["max_exposure_amount"],
        "analysis_focus": analysis_focus,
        "comparison_requested": comparison_requested,
        "requested_subjects": [],
        "requested_date": requested_date,
        "wants_table": wants_table,
        "wants_chart": wants_chart,
        "limit": max(1, requested_limit),
        "question": str(question or "").strip(),
    }


def build_intelligence_overview(
    *,
    selected_date: str | None = None,
    force_refresh: bool = False,
    skip_game_hydration: bool = False,
) -> list[dict[str, Any]]:
    # skip_game_hydration: CANDIDATE GENERATION (_collect_candidates) reads
    # dashboard_games/home_rails directly off each sport dict returned here
    # -- never pass True for any overview that feeds candidate collection,
    # only for callers that need pure metadata (slug/context_label/
    # data_health), e.g. _source_state_fingerprint's change-detection hash.
    # See _build_sport_overview's own comment for the full story.
    effective_date = _effective_date(selected_date)
    sports = _configured_syndicate_sports()
    # Built as an explicit loop rather than a list comprehension so that a
    # crash inside one sport names that sport. This function OOM-killed
    # refresh-worker every ~5 minutes for 16+ hours on 2026-07-26 and the logs
    # could not say which sport was responsible: the per-sport
    # `overview_counts` traces below are emitted in a SECOND pass, after the
    # whole list is built, so a process that dies while building sport N logs
    # nothing at all about sports 1..N. The last line before the OOM was the
    # caller's `post_pull_hot_artifacts`, ~55 seconds and ~3.7GB earlier.
    #
    # Note the shape of the cost: every sport's fully hydrated overview is held
    # simultaneously, so peak is the SUM across sports, not the max.
    # BEGIN/END bracketing makes an unfinished sport visible; the memory sample
    # makes a sport that merely grows-a-lot visible before it becomes fatal.
    # print(..., flush=True) rather than logger.info deliberately -- see #37,
    # logger.info never reaches Render's collector, which is a large part of
    # why this stayed invisible.
    overview: list[dict[str, Any]] = []
    for sport in sports:
        if not isinstance(sport, dict):
            continue
        sport_slug = _safe_text(sport.get("slug"), "sport").lower()
        print(
            f"[intelligence] OVERVIEW_SPORT_BEGIN sport={sport_slug} "
            f"force_refresh={bool(force_refresh)} skip_game_hydration={bool(skip_game_hydration)}",
            flush=True,
        )
        try:
            sport_row = _build_sport_overview(
                sport,
                effective_date,
                force_refresh=force_refresh,
                preserve_requested_date=selected_date is not None,
                skip_game_hydration=skip_game_hydration,
            )
        except Exception as exc:
            print(
                f"[intelligence] OVERVIEW_SPORT_FAILED sport={sport_slug} "
                f"error={type(exc).__name__}: {exc}",
                flush=True,
            )
            raise
        overview.append(sport_row)
        try:
            log_container_memory(
                "overview_sport_end",
                sport=sport_slug,
                sports_done=len(overview),
                sports_total=len([item for item in sports if isinstance(item, dict)]),
            )
        except Exception:
            pass
        print(f"[intelligence] OVERVIEW_SPORT_END sport={sport_slug}", flush=True)
    for sport_overview in overview:
        # Emitted for EVERY sport, not just WNBA. These four counts are the
        # only view of what candidate generation is handed -- _collect_candidates
        # reads dashboard_games and home_rails straight off these dicts, so a
        # sport with zero here can never produce a candidate no matter what
        # the downstream filters do.
        #
        # This was wnba-only, which actively misled a 2026-07-25 investigation
        # into an almost-empty board: the single visible "dashboard_games_count:
        # 0" line was WNBA's, on an All-Star day with one game, and was briefly
        # read as evidence about MLB. Scoping diagnostics to one sport makes the
        # other six look like whatever the instrumented one happens to be doing.
        slug = _safe_text(sport_overview.get("slug"), "sport").lower()
        home_rails = sport_overview.get("home_rails") if isinstance(sport_overview.get("home_rails"), dict) else {}
        pregame_items = home_rails.get("pregame", {}).get("items") if isinstance(home_rails.get("pregame"), dict) else []
        live_items = home_rails.get("live", {}).get("items") if isinstance(home_rails.get("live"), dict) else []
        dashboard_games = sport_overview.get("dashboard_games") if isinstance(sport_overview.get("dashboard_games"), list) else []
        _intel_trace(
            "overview_counts",
            sport=slug,
            context_label=_safe_text(sport_overview.get("context_label"), effective_date),
            pregame_count=len(pregame_items),
            live_count=len(live_items),
            dashboard_games_count=len(dashboard_games),
            data_health=_safe_text(sport_overview.get("data_health"), "unknown"),
        )
    return overview


def _status_context_label_for_sport(slug: str, effective_date: str) -> str:
    slug = str(slug or "").strip().lower()
    if slug in {"mlb", "nba", "wnba", "nhl", "ncaab"}:
        return effective_date
    if slug == "nfl":
        tracked_week = nfl_sources.tracked_week() or {}
        season_value = tracked_week.get("season")
        week_value = tracked_week.get("week")
        if isinstance(season_value, int) and isinstance(week_value, int):
            return f"{season_value} Week {week_value}"
        season_value = nfl_sources.latest_season()
        week_value = nfl_sources.default_week(season_value)
        return f"{season_value} Week {week_value}"
    if slug == "ncaaf":
        week_summaries = ncaaf_sources.week_summaries()
        if week_summaries:
            latest = week_summaries[-1]
            return f"{int(latest.get('season') or ncaaf_sources.default_season())} Week {int(latest.get('week') or ncaaf_sources.default_week())}"
        return f"{ncaaf_sources.default_season()} Week {ncaaf_sources.default_week()}"
    return effective_date


def _status_overview_rows(*, selected_date: str | None = None) -> list[dict[str, Any]]:
    effective_date = _effective_date(selected_date)
    sports = _configured_syndicate_sports()
    overview: list[dict[str, Any]] = []
    for sport in sports:
        if not isinstance(sport, dict):
            continue
        slug = _safe_text(sport.get("slug"), "sport").lower()
        context_label = _status_context_label_for_sport(slug, effective_date)
        overview.append(
            {
                **sport,
                "slug": slug,
                "name": _safe_text(sport.get("name"), slug.upper()),
                "context_label": context_label,
                "data_health": "status",
                "data_warnings": [],
                "active_today": context_label == effective_date,
            }
        )
    return overview


def _artifact_specs_for_sport(sport: dict[str, Any]) -> list[tuple[str, Path]]:
    slug = str(sport.get("slug") or "").strip().lower()
    context_label = str(sport.get("context_label") or "").strip()
    if slug == "mlb" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label):
        season = int(context_label[:4])
        return [
            ("Live lens report", _mlb_repo_artifact_path("data", "live_lens", f"live_lens_report_{context_label.replace('-', '_')}.json")),
            ("Live lens log", _mlb_repo_artifact_path("data", "live_lens", f"live_lens_{context_label.replace('-', '_')}.jsonl")),
            (
                "Season betting day",
                _mlb_repo_artifact_path(
                    "data",
                    "eval",
                    "seasons",
                    str(season),
                    "betting_day_payloads_retuned",
                    f"season_betting_day_{season}_{context_label.replace('-', '_')[5:]}.json",
                ),
            ),
        ]
    if slug == "nba" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label):
        season = int(context_label[:4])
        return [
            ("Recommendations slate", nba_processed_path(f"recommendations_slate_{context_label}.json")),
            ("Props recommendations", nba_processed_path(f"props_recommendations_{context_label}.csv")),
            ("Live state snapshot", nba_live_snapshot_path(f"live_state_{context_label}.jsonl")),
            ("Season betting day", nba_season_betting_card_day_path(season, context_label, profile="retuned")),
        ]
    if slug == "wnba" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label):
        season = int(context_label[:4])
        return [
            ("Recommendations slate", _wnba_repo_artifact_path(f"recommendations_slate_{context_label}.json")),
            ("Props recommendations", _wnba_repo_artifact_path(f"props_recommendations_{context_label}.csv")),
            ("Live state snapshot", _wnba_repo_artifact_path("live_snapshots", f"live_state_{context_label}.jsonl")),
            ("Season betting day", _wnba_repo_artifact_path(f"season_betting_card_day_{season}_retuned_{context_label}.json")),
        ]
    if slug == "nhl" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label):
        return [
            ("Recommendations", nhl_recommendation_path(context_label)),
            ("Props recommendations", nhl_processed_path(f"props_recommendations_{context_label}.csv")),
            ("Scoreboard snapshot", nhl_scoreboard_snapshot_path(context_label)),
            ("Props lines snapshot", nhl_props_lines_snapshot_path(context_label)),
        ]
    if slug == "nfl":
        week_match = re.search(r"(?P<season>\d{4})\s+Week\s+(?P<week>\d+)", context_label)
        if week_match:
            season = int(week_match.group("season"))
            week = int(week_match.group("week"))
            return [
                ("Weekly recommendations", nfl_sources.recommendation_path(week, season=season)),
                ("Current week", nfl_sources.data_path("current_week.json")),
            ]
    if slug == "ncaaf":
        week_match = re.search(r"(?P<season>\d{4})\s+Week\s+(?P<week>\d+)", context_label)
        if week_match:
            week = int(week_match.group("week"))
            return [
                ("Recommendation summary", ncaaf_sources.summary_path(week)),
                ("Summary index", ncaaf_sources.data_path("recommendations_summary", "index.json")),
            ]
    if slug == "ncaab" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label):
        root = ncaab_sources._source_roots()[0]
        return [
            ("Recommendations", root / "api" / "recommendations" / f"recommendations_{context_label}.json"),
            ("Live state", root / "api" / "live_state" / f"live_state_{context_label}.json"),
            ("Live lines", root / "api" / "live_lines" / f"live_lines_{context_label}.json"),
        ]
    return []


def _first_existing_artifact_path(*, env_var: str, local_dir_name: str, parts: tuple[str, ...]) -> Path:
    # Real production bug (2026-07-23): default_mlb_source_root()/
    # default_wnba_source_root() resolve via preferred_source_roots(), which
    # returns SYNDICATE_*_SOURCE_ROOT verbatim -- no "source_artifacts"
    # segment -- once that env var is set (true in every deployed
    # environment). Some generated artifacts (confirmed: MLB's live_lens
    # report) live under a "source_artifacts" subdirectory there instead;
    # others (confirmed: MLB's statcast player-features file) live at the
    # plain root. Rather than guess which convention a given artifact uses,
    # check every candidate root preferred_artifact_roots returns (source_
    # artifacts-first, same resolver MLB/WNBA's OWN working artifact readers
    # already use -- e.g. daily_top_props_path, current_odds_root_for_sport)
    # and use whichever one actually has the file, falling back to the
    # highest-priority candidate if none exist yet.
    candidates = preferred_artifact_roots(__file__, env_var=env_var, local_dir_name=local_dir_name)
    resolved = [root.joinpath(*parts) for root in candidates] or [Path(*parts)]
    for candidate_path in resolved:
        if candidate_path.exists():
            return candidate_path
    return resolved[0]


def _mlb_repo_artifact_path(*parts: str) -> Path:
    return _first_existing_artifact_path(env_var="SYNDICATE_MLB_SOURCE_ROOT", local_dir_name="mlb_source", parts=parts)


def _wnba_repo_artifact_path(*parts: str) -> Path:
    return _first_existing_artifact_path(env_var="SYNDICATE_WNBA_SOURCE_ROOT", local_dir_name="wnba_source", parts=("data", "processed", *parts))


def _shard_key_from_context_label(slug: str, context_label: str) -> str:
    label = _safe_text(context_label, "").strip()
    if slug in {"nfl", "ncaaf"}:
        week_match = re.search(r"(?P<season>\d{4})\s+Week\s+(?P<week>\d+)", label)
        if week_match:
            return shard_key_for_week(int(week_match.group("season")), int(week_match.group("week")))
        return resolve_current_shard_key(slug, central_today_iso())
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", label):
        return label
    return resolve_current_shard_key(slug, central_today_iso())


def _load_odds_history_payload_for_sport(slug: str, shard_key: str) -> dict[str, Any] | None:
    sport_slug = _safe_text(slug, "sport").lower()
    payload = _canonical_load_odds_history_payload_for_sport(sport_slug, shard_key)
    if not isinstance(payload, dict):
        _intel_trace(
            "odds_history_input",
            sport=sport_slug,
            shard_key=shard_key,
            present=False,
            entry_count=0,
        )
        return None
    markets = payload.get("markets") if isinstance(payload.get("markets"), dict) else {}
    market_keys = list(markets.keys()) if isinstance(markets, dict) else []
    _intel_trace(
        "odds_history_input",
        sport=sport_slug,
        shard_key=shard_key,
        present=True,
        entry_count=len(market_keys),
        sample_market_keys=market_keys[:5],
    )
    return payload


def _odds_history_payloads_by_sport(overview: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for sport in overview:
        if not isinstance(sport, dict):
            continue
        slug = _safe_text(sport.get("slug"), "sport").lower()
        if not slug or slug in payloads:
            continue
        shard_key = _shard_key_from_context_label(slug, _safe_text(sport.get("context_label"), ""))
        payload = _load_odds_history_payload_for_sport(slug, shard_key)
        if isinstance(payload, dict):
            payloads[slug] = payload
    _intel_trace(
        "odds_history_summary",
        odds_data_present=bool(payloads),
        sports_loaded=len(payloads),
        sample_sports=sorted(payloads.keys())[:5],
    )
    return payloads


def _parse_odds_history_market_key(market_key: Any) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for part in str(market_key or "").split("|"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        normalized_key = _safe_text(key, "").lower()
        normalized_value = _normalized_market_text(value)
        if normalized_key and normalized_value:
            parsed[normalized_key] = normalized_value
    return parsed


def _candidate_selection_text(candidate: dict[str, Any]) -> str:
    return _normalized_market_text(_safe_text(candidate.get("pick"), _safe_text(candidate.get("name"), "")))


_GAME_ONLY_ODDS_HISTORY_MARKET_TYPES = {"h2h", "spreads", "totals", "moneyline", "spread", "total"}


def _candidate_odds_history_match_score(candidate: dict[str, Any], market_key: Any, state: Mapping[str, Any]) -> float:
    parsed_key = _parse_odds_history_market_key(market_key)
    if not parsed_key:
        return 0.0

    score = 0.0
    candidate_matchup = _normalized_market_text(_safe_text(candidate.get("matchup"), ""))
    candidate_market = _normalized_market_text(_safe_text(candidate.get("market"), ""))
    # _candidate_subject_key() only ever returns non-None for candidate_type
    # == "prop" (by its own explicit design, since its other callers --
    # dedup, correlated-parlay-leg matching -- are prop-specific too; not
    # touched here to avoid widening those). Steam candidates carry their
    # own real subject under "subject_key"/"player_name"/"entity" instead
    # (set in _steam_candidates_for_sport) -- fall back to those so the
    # cross-market guard below has real identity text to check for BOTH
    # candidate types, not just props.
    subject_source = _candidate_subject_key(candidate) or candidate.get("subject_key") or candidate.get("player_name") or candidate.get("entity")
    candidate_subject = _normalized_market_text(_safe_text(subject_source, ""))
    candidate_team = _normalized_market_text(_safe_text(_candidate_team_key(candidate), ""))
    candidate_selection = _candidate_selection_text(candidate)
    candidate_selection_direction = _candidate_selection_direction(candidate)
    candidate_selection_hint = "over" if candidate_selection_direction > 0 else "under" if candidate_selection_direction < 0 else ""
    entry_event = " ".join(
        _safe_text(parsed_key.get(field), "")
        for field in ("event_key", "event_id", "matchup", "home_team", "away_team", "player_name", "player_key", "team", "team_key")
    ).strip()
    entry_market = _safe_text(parsed_key.get("market"), "")
    entry_selection = _safe_text(parsed_key.get("selection"), "")
    entry_book = _safe_text(parsed_key.get("bookmaker") or parsed_key.get("book"), "")

    # A player-prop candidate must never adopt a GAME-level market's odds
    # history (h2h/spreads/totals) just because it happens to share the same
    # matchup text -- confirmed live 2026-07-24: a Tomoyuki Sugano
    # strikeouts-prop candidate was showing the Milwaukee Brewers
    # MONEYLINE's price movement as its own "Move" value, because the
    # matchup-text-overlap scoring below (+2.0 per matching field) alone
    # cleared the >0.0 acceptance threshold in _candidate_odds_history_state
    # even though nothing about the market or the player actually
    # corresponded. Game-level candidates are unaffected: their own market
    # text never textually overlaps entry_market either (display label
    # "Moneyline" vs raw API type "h2h"), so that comparison was always a
    # soft bonus, not a hard requirement -- only props need this extra gate,
    # since only props have a real player identity to check against.
    #
    # Confirmed live 2026-07-31: soccer "steam move" candidates hit the
    # identical failure this gate was built for, just via candidate_type ==
    # "steam" instead of "prop" -- all 120 steam candidates on one day's
    # board converged onto a single unrelated game's odds history (one
    # NYCFC/Toronto FC entry), because "steam" was never covered here and
    # the soft matchup-text bonus alone was enough to clear the >0.0
    # threshold for candidates with no real overlap at all. A steam
    # candidate's own subject (_candidate_subject_key) is exactly as real an
    # identity as a prop's -- it's a player name for a player-level steam
    # move, or a team name for a game-level one -- so the same hard gate
    # applies equally well to both.
    if _safe_text(candidate.get("candidate_type"), "") in ("prop", "steam") and entry_market.strip().lower() in _GAME_ONLY_ODDS_HISTORY_MARKET_TYPES:
        if not candidate_subject or candidate_subject not in entry_event:
            return 0.0

    for value in (candidate_matchup, candidate_subject, candidate_team, candidate_selection):
        if not value or not entry_event:
            continue
        if value == entry_event or value in entry_event or entry_event in value:
            score += 2.0

    if candidate_market and entry_market:
        if candidate_market == entry_market or candidate_market in entry_market or entry_market in candidate_market:
            score += 3.0

    if candidate_selection and entry_selection:
        if candidate_selection == entry_selection or candidate_selection in entry_selection or entry_selection in candidate_selection:
            score += 2.5
    if candidate_selection_hint and entry_selection and candidate_selection_hint in entry_selection:
        score += 1.0

    if entry_book and _normalized_market_text(_safe_text(candidate.get("book"), _safe_text(candidate.get("bookmaker"), ""))):
        candidate_book = _normalized_market_text(_safe_text(candidate.get("book"), _safe_text(candidate.get("bookmaker"), "")))
        if candidate_book == entry_book or candidate_book in entry_book or entry_book in candidate_book:
            score += 0.5

    candidate_line = _numeric_hint(candidate.get("line"))
    state_line = _numeric_hint(state.get("last_line"))
    if candidate_line is not None and state_line is not None:
        score += max(0.0, 1.5 - min(abs(candidate_line - state_line), 1.5))

    return score


def _build_odds_history_player_index(
    odds_history: dict[str, Any] | None,
) -> tuple[dict[str, list[tuple[str, dict[str, Any]]]], list[tuple[str, dict[str, Any]]]]:
    """Splits a sport's odds-history markets into per-player buckets (keyed
    by the market key's own player_name/player_key field) plus a small
    remainder list of unattributed (game-level: moneyline/spread/total)
    entries. _candidate_odds_history_state used to linear-scan every market
    for every candidate -- fine when MLB only had ~33 game-level entries,
    but confirmed live 2026-07-24: once MLB prop odds-history started being
    written (a same-day fix), that payload grew to 3,366+ entries, and the
    O(candidates * markets) scan made one compute cycle take 147s instead
    of ~1.3s, directly contributing to a production worker timeout / empty
    board incident. A prop candidate only ever needs its own player's
    handful of entries, so bucketing by player_name turns that scan into a
    small, O(1)-lookup pool instead.
    """
    by_player: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    unattributed: list[tuple[str, dict[str, Any]]] = []
    markets = (odds_history or {}).get("markets") if isinstance(odds_history, dict) else None
    if not isinstance(markets, dict):
        return by_player, unattributed
    for market_key, state in markets.items():
        if not isinstance(state, dict):
            continue
        parsed = _parse_odds_history_market_key(market_key)
        player = _normalized_market_text(parsed.get("player_name") or parsed.get("player_key") or "")
        if player:
            by_player.setdefault(player, []).append((str(market_key), state))
        else:
            unattributed.append((str(market_key), state))
    return by_player, unattributed


def _candidate_odds_history_state(
    candidate: dict[str, Any], odds_history_index: tuple[dict[str, list[tuple[str, dict[str, Any]]]], list[tuple[str, dict[str, Any]]]]
) -> tuple[str, dict[str, Any] | None]:
    by_player, unattributed = odds_history_index
    if not by_player and not unattributed:
        return "", None

    subject_key = _normalized_market_text(_safe_text(candidate.get("player_name"), "")) or _normalized_market_text(
        _safe_text(_candidate_subject_key(candidate), "")
    )
    pool = list(unattributed)
    if subject_key and subject_key in by_player:
        pool.extend(by_player[subject_key])
    if not pool:
        return "", None

    best_key = ""
    best_state: dict[str, Any] | None = None
    best_score = 0.0
    for market_key, state in pool:
        score = _candidate_odds_history_match_score(candidate, market_key, state)
        if score > best_score:
            best_key = market_key
            best_score = score
            best_state = state

    if best_score <= 0.0:
        return "", None
    return best_key, best_state


def _candidate_odds_history_context(
    candidate: dict[str, Any],
    odds_history_index: tuple[dict[str, list[tuple[str, dict[str, Any]]]], list[tuple[str, dict[str, Any]]]],
) -> dict[str, Any] | None:
    market_key, history_state = _candidate_odds_history_state(candidate, odds_history_index)
    market_data = candidate.get("market_data") if isinstance(candidate.get("market_data"), dict) else {}
    movement_history = market_data.get("movement_history") if isinstance(market_data.get("movement_history"), list) else []
    opening_line = _numeric_hint(market_data.get("opening_line"))
    current_line = _numeric_hint(market_data.get("current_line"))

    if history_state is None:
        if opening_line is None and current_line is None and not movement_history:
            return None
        if current_line is None:
            current_line = _numeric_hint(candidate.get("line"))
        previous_line = opening_line
        if previous_line is None and len(movement_history) >= 2:
            previous_line = _numeric_hint(movement_history[-2].get("line"))
            if current_line is None:
                current_line = _numeric_hint(movement_history[-1].get("line"))
        if current_line is None and movement_history:
            current_line = _numeric_hint(movement_history[-1].get("line"))
        if previous_line is None and current_line is not None and movement_history:
            previous_line = _numeric_hint(movement_history[0].get("line"))
        if current_line is None and previous_line is None:
            return None
        delta = current_line - previous_line if current_line is not None and previous_line is not None else None
        percent_change = None
        if current_line is not None and previous_line not in (None, 0):
            percent_change = ((current_line - previous_line) / abs(previous_line)) * 100.0
        trend = "flat"
        if delta is not None:
            if delta > 0:
                trend = "up"
            elif delta < 0:
                trend = "down"
        return {
            "market_key": market_key or None,
            "last_line": current_line if current_line is not None else previous_line,
            "previous_line": previous_line,
            "delta": delta,
            "movement": trend,
            "trend": trend,
            "recent_movement_trend": trend,
            "percent_change": percent_change,
            "last_updated": None,
            "history": movement_history,
        }

    history = history_state.get("history") if isinstance(history_state.get("history"), list) else []
    last_line = _numeric_hint(history_state.get("last_line"))
    previous_line = _numeric_hint(history_state.get("previous_line"))
    delta = _numeric_hint(history_state.get("delta"))
    percent_change = _numeric_hint(history_state.get("percent_change"))
    movement = _safe_text(history_state.get("movement"), "flat") or "flat"
    last_updated = _safe_text(history_state.get("last_updated"), "") or None

    if last_line is None and current_line is not None:
        last_line = current_line
    if previous_line is None and len(history) >= 2:
        previous_line = _numeric_hint((history[-2] or {}).get("current_line"))
    if delta is None and last_line is not None and previous_line is not None:
        delta = last_line - previous_line
    if percent_change is None and last_line is not None and previous_line not in (None, 0):
        percent_change = ((last_line - previous_line) / abs(previous_line)) * 100.0
    if movement == "flat" and delta is not None:
        if delta > 0:
            movement = "up"
        elif delta < 0:
            movement = "down"

    return {
        "market_key": market_key or None,
        "last_line": last_line,
        "previous_line": previous_line,
        "delta": delta,
        "movement": movement,
        "trend": movement,
        "recent_movement_trend": movement,
        "percent_change": percent_change,
        "last_updated": last_updated,
        "history": history,
    }


def _prop_merge_dedup_key(candidate: dict[str, Any]) -> tuple[str, str, str, float | None, int] | None:
    # Board audit, 2026-07-31: widened from "prop" only to also cover
    # "steam" -- a steam candidate and a prop candidate can describe the
    # identical real-world bet (same player/market/line/side), sourced from
    # two entirely independent pipelines (steam = continuous line-movement
    # detection, prop = the analytical "top props"/recommendation
    # artifacts), and neither dedupes against the other. Confirmed live:
    # the same Miguel Amaya Over 0.5 Hits bet showed simultaneously as
    # "-123" (prop, no live_projection) and "+100" (steam, live_projection
    # 1.1) -- two different, unreconciled prices for one real bet. See
    # _merge_duplicate_prop_candidates for the merge policy once these
    # share an identity.
    if _safe_text(candidate.get("candidate_type"), "") not in ("prop", "steam"):
        return None
    sport_slug = _safe_text(candidate.get("sport_slug"), "").lower()
    player_name_text = _normalized_market_text(_safe_text(candidate.get("player_name"), ""))
    # Board-alignment audit, found live 2026-08-01 against a real live WNBA
    # game: a candidate whose upstream builder never set a real player_name
    # (traced to a rank-card/pregame-only pipeline, not yet root-caused to
    # its exact source) had the ENTIRE pick text ("Alyssa Thomas UNDER 8.5
    # AST") land in player_name instead. Since that's truthy, it always won
    # over _candidate_subject_key's careful "split on over/under" parse,
    # so this candidate's dedup key never matched its correctly-labeled
    # twin from a different pipeline (subject "Alyssa Thomas") -- they
    # never merged, and the mislabeled one stayed stuck with no
    # live_projection/actual even once its game went live. A real player
    # name is never itself "... over ..."/"... under ..." text, so this is
    # a safe, general tell that player_name actually holds pick text --
    # in that case prefer _candidate_subject_key's parse of "name" instead
    # of trusting the corrupted value.
    if player_name_text and any(f" {marker} " in f" {player_name_text} " for marker in ("over", "under")):
        player_name_text = ""
    subject = player_name_text or _normalized_market_text(_safe_text(_candidate_subject_key(candidate), ""))
    if not subject:
        return None
    # Deliberately bypasses _candidate_market_key/_candidate_market_focuses
    # here: those prefer an already-set candidate["market_key"] field
    # verbatim (e.g. "pitcher strikeouts") over the canonical alias-mapped
    # key (e.g. "strikeouts"), which is exactly what let two duplicate
    # candidates for the same market compare unequal. Calling
    # _market_key_from_text directly always canonicalizes through
    # _MARKET_FOCUS_ALIASES, so "strikeouts" and "pitcher strikeouts" match.
    market = _market_key_from_text(candidate.get("market"), allow_fallback=True)
    if not market:
        return None
    line = _numeric_hint(candidate.get("line"))
    line_bucket = round(line * 2.0) / 2.0 if line is not None else None
    direction = _candidate_selection_direction(candidate)
    return (sport_slug, subject, market, line_bucket, direction)


def _prop_candidate_completeness_score(candidate: dict[str, Any]) -> float:
    score = 0.0
    if _numeric_hint(candidate.get("projected")) is not None:
        score += 3.0
    score += min(len(_safe_text(candidate.get("detail"), "")) / 100.0, 3.0)
    market_data = candidate.get("market_data") if isinstance(candidate.get("market_data"), dict) else {}
    movement = market_data.get("movement") if isinstance(market_data.get("movement"), dict) else {}
    if movement.get("history"):
        score += 1.0
    if _safe_text(candidate.get("headshot_url"), ""):
        score += 0.5
    return score


_PROP_MERGE_BACKFILL_FIELDS = (
    "projected",
    "sim_projection",
    "headshot_url",
    "display_pills",
    "hero_live_box",
    "hero_sim_box",
)

# Unlike the backfill-if-blank fields above, a short-but-present detail/
# writeup/summary from the "winning" candidate must not block adopting a
# duplicate's longer, more informative text -- e.g. "Over 4+ Strikeouts |
# Pitcher top props" (non-blank, but says nothing a reader couldn't already
# see elsewhere on the row) versus a full model-reasoning paragraph. Always
# keep whichever is longer rather than only filling in when blank.
_PROP_MERGE_PREFER_LONGER_TEXT_FIELDS = ("detail", "writeup", "summary")

# Board audit, 2026-07-31: unlike the backfill-if-blank fields above, these
# must come from the steam candidate in a merged group WHENEVER one exists
# -- even overwriting a non-blank value already on the prop side. A prop
# candidate's price/live-state fields have no freshness guarantee (the
# "top props" artifact refreshes on its own cadence, unrelated to real-time
# market movement); a steam candidate's whole reason for existing is
# tracking the CURRENT sportsbook line via continuous odds polling. Backfill
# -if-blank would leave a stale-but-present prop price untouched even when a
# fresher steam price is sitting right there in the same group -- exactly
# the Miguel Amaya Over 0.5 Hits case (-123 prop vs +100 steam) that
# motivated this. Price and its dependent fields (edge/confidence/win%)
# always move together from the same source, so a merged row never pairs
# one source's price with a different source's edge computed against a
# different price.
_STEAM_PRICE_OVERRIDE_FIELDS = (
    "odds",
    "american_odds",
    "line",
    "live_projection",
    "actual",
    "is_live",
    "status_display",
    "game_state",
    "line_odds_movement",
    "steam",
    "edge",
    "edge_pct",
    "confidence",
    "model_probability",
    "implied_probability",
    "adjusted_edge",
)

# Board audit follow-up, 2026-07-31: a live-lens-sourced "prop" candidate
# (_mlb_live_lens_prop_candidates_from_artifact -- candidate_type="prop"
# like every other prop, not "steam") is just as fresh an authority on
# live-state as a steam candidate -- it's built directly from the same
# continuously-refreshed live-lens report -- but the override treatment
# above only ever triggered when the group's live member happened to be
# typed "steam". Confirmed live: a stale top-props candidate
# (status_display="Warmup", is_live=False, from a once/day snapshot) and a
# fresh live-lens duplicate for the identical bet (same subject/market/
# line/direction, is_live=True, real actual/live_projection) merged via
# this function, kept the stale one as primary (it has detail/headshot text
# giving it a higher completeness score -- a live-lens row never carries
# those), and then silently dropped the live-lens row's freshness because
# none of these fields are in the blank-only backfill list above. Board
# symptom: games the board's own game chips correctly showed live still
# showed nearly every prop candidate stuck at lane "pregame". Unlike the
# steam fields above, deliberately NOT bundling price/edge/confidence here
# -- a live-lens row isn't a confirmed fresher price the way a steam
# candidate is, only fresher live-state. Same field subset
# _apply_live_state_context_to_candidates already trusts for this exact
# purpose on a single (non-duplicate-merged) candidate.
_LIVE_STATE_ONLY_OVERRIDE_FIELDS = (
    "is_live",
    "is_final",
    "status_display",
    "game_state",
    "live_projection",
    "actual",
)


def _field_is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or value.strip() == "-"
    if isinstance(value, (list, dict)):
        return not value
    return False


def _merge_duplicate_prop_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # 2026-07-24 fix: the identical prop bet (same player/market/line/side)
    # can be independently produced by more than one upstream pipeline --
    # e.g. MLB's "top props" artifact (home_rails.pregame, has projected/odds
    # but a short generic detail) and a game's own game_market_recommendations
    # list (has a rich narrative writeup but no projected value) both cover
    # the same prop under slightly different pick/market text, and neither
    # pipeline dedupes against the other. Confirmed live 2026-07-24 (a
    # Tomoyuki Sugano strikeouts candidate shown twice: "Over 4+" with
    # Projected 4.9 and no reasoning, and "OVER Tomoyuki Sugano" with a full
    # reasoning paragraph but Projected blank). Merge instead of dropping one
    # wholesale: keep the more complete candidate as the base and backfill
    # any of its blank fields from the dropped duplicate, so nothing
    # (projection, reasoning, headshot, etc.) is lost either way.
    #
    # Board audit, 2026-07-31: widened to also merge a "steam" candidate
    # sharing the same identity (_prop_merge_dedup_key now covers both
    # types). Steam and prop disagree on which field should win: steam's
    # price/live-state is always the fresher one (see
    # _STEAM_PRICE_OVERRIDE_FIELDS), while prop's analytical fields
    # (projected/detail/writeup/headshot) are what steam candidates never
    # carry in the first place. So a mixed group merges in two passes: the
    # existing "most complete analytical candidate wins, backfill the rest"
    # logic runs first (unchanged, and it already correctly ignores a steam
    # candidate for this purpose -- steam's projected/detail are always
    # blank, so its own completeness score is always low), then the steam
    # candidate's price fields are applied on top, unconditionally.
    groups: dict[tuple, list[int]] = {}
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        key = _prop_merge_dedup_key(candidate)
        if key is None:
            continue
        groups.setdefault(key, []).append(index)

    merged_at: dict[int, dict[str, Any]] = {}
    dropped: set[int] = set()
    for indices in groups.values():
        if len(indices) < 2:
            continue
        steam_index = next(
            (i for i in indices if _safe_text(candidates[i].get("candidate_type"), "") == "steam"),
            None,
        )
        analytical_indices = [i for i in indices if i != steam_index] if steam_index is not None else list(indices)
        if not analytical_indices:
            analytical_indices = [steam_index]
        ordered = sorted(analytical_indices, key=lambda i: _prop_candidate_completeness_score(candidates[i]), reverse=True)
        primary_index = ordered[0]
        merged = dict(candidates[primary_index])
        for other_index in ordered[1:]:
            other = candidates[other_index]
            for field in _PROP_MERGE_BACKFILL_FIELDS:
                if _field_is_blank(merged.get(field)) and not _field_is_blank(other.get(field)):
                    merged[field] = other.get(field)
            for field in _PROP_MERGE_PREFER_LONGER_TEXT_FIELDS:
                other_text = _safe_text(other.get(field), "")
                merged_text = _safe_text(merged.get(field), "")
                if len(other_text) > len(merged_text):
                    merged[field] = other.get(field)
        if steam_index is not None and steam_index != primary_index:
            steam_candidate = candidates[steam_index]
            for field in _STEAM_PRICE_OVERRIDE_FIELDS:
                value = steam_candidate.get(field)
                if not _field_is_blank(value):
                    merged[field] = value
            # A merged row IS a confirmed real-time price move on a real
            # prop -- reflect that in candidate_type so the board's
            # steam-only filter still finds it (the player-props filter is
            # unaffected: it keys off truthy player_name, not
            # candidate_type, so this candidate keeps showing there too).
            merged["candidate_type"] = "steam"
            merged["is_steam_confirmed"] = True
        live_index = next(
            (i for i in indices if i != primary_index and bool(candidates[i].get("is_live"))),
            None,
        )
        if live_index is not None:
            live_candidate = candidates[live_index]
            for field in _LIVE_STATE_ONLY_OVERRIDE_FIELDS:
                value = live_candidate.get(field)
                if not _field_is_blank(value):
                    merged[field] = value
        merged["merged_from"] = sorted(
            {_safe_text(candidates[i].get("candidate_type"), "") for i in indices if _safe_text(candidates[i].get("candidate_type"), "")}
        )
        for i in indices:
            if i != primary_index:
                dropped.add(i)
        merged_at[primary_index] = merged

    if not dropped:
        return candidates
    result: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if index in dropped:
            continue
        result.append(merged_at.get(index, candidate))
    return result


def _game_side_merge_dedup_key(candidate: dict[str, Any]) -> tuple[str, str, str, str, float | None] | None:
    """Board audit follow-up, 2026-07-31: a team-level (moneyline/spread)
    steam candidate had no merge counterpart with an equivalent "game"-type
    Moneyline/Spread candidate for the same real bet -- a gap the
    prop/steam merge above doesn't cover, since it excludes candidate_type
    == "game" entirely and a team-level steam candidate's player_name is
    deliberately nulled (a team-total steam move must not masquerade as a
    "player prop"), leaving it with no subject _prop_merge_dedup_key can
    resolve. Zero live occurrences confirmed at the time this was built
    (flagged, then fixed proactively), but the gap was real.

    Deliberately a SEPARATE function/pass from _prop_merge_dedup_key rather
    than folding "game" into that gate directly: a team abbreviation is
    materially weaker identity than a player's full name (e.g. "NYY" isn't
    unique the way "Miguel Amaya" is -- two different games could plausibly
    share a team/market/line at some point), so this REQUIRES the real game
    (gamePk/game_id/event_id) to match too, not just team+market+line --
    unlike the player-prop path, where subject alone is strong enough on
    its own without a game-identity requirement. Total markets (no team
    side at all) are excluded entirely: merging by market+line alone with
    no team and no per-side identity would risk conflating two unrelated
    games that happen to share a total line.
    """
    candidate_type = _safe_text(candidate.get("candidate_type"), "")
    if candidate_type not in ("game", "steam"):
        return None
    sport_slug = _safe_text(candidate.get("sport_slug"), "").lower()
    if not sport_slug:
        return None
    game_identity = _safe_text(candidate.get("gamePk") or candidate.get("game_id") or candidate.get("event_id"), "")
    if not game_identity:
        return None
    market = _market_key_from_text(candidate.get("market"), allow_fallback=True)
    if market not in ("moneyline", "spread"):
        return None
    team = _candidate_team_key(candidate)
    if not team:
        return None
    line = _numeric_hint(candidate.get("line"))
    line_bucket = round(line * 2.0) / 2.0 if line is not None else None
    return (sport_slug, game_identity, market, team, line_bucket)


def _merge_duplicate_game_side_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Mirrors _merge_duplicate_prop_candidates' merge policy exactly (same
    # completeness-first analytical base, same "steam price always wins"
    # rule -- see _STEAM_PRICE_OVERRIDE_FIELDS' docstring for why) against
    # groups formed by _game_side_merge_dedup_key instead. Kept as its own
    # pass rather than folding into the function above so the
    # already-verified prop/steam merge path is never touched by this
    # newer, more narrowly-scoped extension.
    groups: dict[tuple, list[int]] = {}
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        key = _game_side_merge_dedup_key(candidate)
        if key is None:
            continue
        groups.setdefault(key, []).append(index)

    merged_at: dict[int, dict[str, Any]] = {}
    dropped: set[int] = set()
    for indices in groups.values():
        if len(indices) < 2:
            continue
        steam_index = next(
            (i for i in indices if _safe_text(candidates[i].get("candidate_type"), "") == "steam"),
            None,
        )
        analytical_indices = [i for i in indices if i != steam_index] if steam_index is not None else list(indices)
        if not analytical_indices:
            analytical_indices = [steam_index]
        ordered = sorted(analytical_indices, key=lambda i: _prop_candidate_completeness_score(candidates[i]), reverse=True)
        primary_index = ordered[0]
        merged = dict(candidates[primary_index])
        for other_index in ordered[1:]:
            other = candidates[other_index]
            for field in _PROP_MERGE_BACKFILL_FIELDS:
                if _field_is_blank(merged.get(field)) and not _field_is_blank(other.get(field)):
                    merged[field] = other.get(field)
            for field in _PROP_MERGE_PREFER_LONGER_TEXT_FIELDS:
                other_text = _safe_text(other.get(field), "")
                merged_text = _safe_text(merged.get(field), "")
                if len(other_text) > len(merged_text):
                    merged[field] = other.get(field)
        if steam_index is not None and steam_index != primary_index:
            steam_candidate = candidates[steam_index]
            for field in _STEAM_PRICE_OVERRIDE_FIELDS:
                value = steam_candidate.get(field)
                if not _field_is_blank(value):
                    merged[field] = value
            merged["candidate_type"] = "steam"
            merged["is_steam_confirmed"] = True
        # Same gap as _merge_duplicate_prop_candidates' identical block --
        # a live-lens-sourced game-level candidate can be just as fresh an
        # authority on live-state as a steam candidate without being typed
        # "steam" itself.
        live_index = next(
            (i for i in indices if i != primary_index and bool(candidates[i].get("is_live"))),
            None,
        )
        if live_index is not None:
            live_candidate = candidates[live_index]
            for field in _LIVE_STATE_ONLY_OVERRIDE_FIELDS:
                value = live_candidate.get(field)
                if not _field_is_blank(value):
                    merged[field] = value
        merged["merged_from"] = sorted(
            {_safe_text(candidates[i].get("candidate_type"), "") for i in indices if _safe_text(candidates[i].get("candidate_type"), "")}
        )
        for i in indices:
            if i != primary_index:
                dropped.add(i)
        merged_at[primary_index] = merged

    if not dropped:
        return candidates
    result: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if index in dropped:
            continue
        result.append(merged_at.get(index, candidate))
    return result


def _enrich_candidates_with_odds_history(candidates: list[dict[str, Any]], odds_history_by_sport: dict[str, dict[str, Any]] | None) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    # Indexed once per sport rather than re-scanning the full odds-history
    # payload for every candidate -- see _build_odds_history_player_index's
    # docstring for the production incident this was built to fix.
    index_by_sport: dict[str, tuple[dict[str, list[tuple[str, dict[str, Any]]]], list[tuple[str, dict[str, Any]]]]] = {}
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        payload = dict(candidate)
        payload = _attach_market_data(payload)
        sport_slug = _safe_text(payload.get("sport_slug"), "sport").lower()
        if sport_slug not in index_by_sport:
            odds_history = (odds_history_by_sport or {}).get(sport_slug) if isinstance(odds_history_by_sport, dict) else None
            index_by_sport[sport_slug] = _build_odds_history_player_index(odds_history)
        movement_context = _candidate_odds_history_context(payload, index_by_sport[sport_slug])
        if movement_context:
            market_data = payload.get("market_data") if isinstance(payload.get("market_data"), dict) else {}
            if movement_context.get("history") and not market_data.get("movement_history"):
                market_data["movement_history"] = movement_context.get("history")
            market_data["movement"] = movement_context
            payload["market_data"] = market_data
            payload["movement"] = movement_context
            payload["delta"] = movement_context.get("delta")
            payload["percent_change"] = movement_context.get("percent_change")
            payload["recent_movement_trend"] = movement_context.get("recent_movement_trend")
            payload["last_updated"] = movement_context.get("last_updated")
            payload["odds_history"] = {
                "market_key": movement_context.get("market_key"),
                "last_line": movement_context.get("last_line"),
                "previous_line": movement_context.get("previous_line"),
                "delta": movement_context.get("delta"),
                "movement": movement_context.get("movement"),
                "trend": movement_context.get("trend") or movement_context.get("movement"),
                "percent_change": movement_context.get("percent_change"),
                "last_updated": movement_context.get("last_updated"),
            }
        enriched.append(payload)
    return enriched


def _path_status(path: Path, tracked: set[str]) -> dict[str, Any]:
    relative_path = _relative_repo_path(path)
    inside_repo = not Path(relative_path).is_absolute() and not relative_path.startswith("..")
    exists = False
    try:
        exists = path.exists()
    except OSError:
        exists = False
    tracked_here = inside_repo and relative_path in tracked
    return {
        "path": relative_path,
        "exists": exists,
        "tracked": tracked_here,
        "inside_repo": inside_repo,
    }


def _coerce_date_token(value: str) -> str | None:
    match = _DATE_TOKEN_RE.search(str(value or ""))
    if not match:
        return None
    token = match.group("date")
    if re.fullmatch(r"\d{8}", token):
        return f"{token[:4]}-{token[4:6]}-{token[6:8]}"
    return token


def _question_requested_date(question: str) -> str | None:
    lowered = str(question or "").strip().lower()
    if not lowered:
        return None
    explicit = _coerce_date_token(lowered)
    if explicit:
        return explicit
    today_value = central_today_iso()
    if re.search(r"\btoday\b", lowered):
        return today_value
    if re.search(r"\btomorrow\b", lowered):
        return (date.fromisoformat(today_value) + timedelta(days=1)).isoformat()
    if re.search(r"\byesterday\b", lowered):
        return (date.fromisoformat(today_value) - timedelta(days=1)).isoformat()
    return None


def _path_date_token(path: Path) -> str | None:
    for candidate in (path.name, path.stem, path.parent.name, path.as_posix()):
        token = _coerce_date_token(candidate)
        if token:
            return token
    return None


def _latest_matching_path(
    directory: Path,
    pattern: str,
    *,
    requested_date: str | None = None,
    max_age_days: int | None = None,
) -> Path | None:
    try:
        candidates = [path for path in directory.glob(pattern) if path.is_file()]
    except OSError:
        return None
    if not candidates:
        return None
    requested = str(requested_date or "").strip() or None
    dated: list[tuple[str, Path]] = []
    for path in candidates:
        token = _path_date_token(path)
        if token is None:
            continue
        if requested and token > requested:
            continue
        dated.append((token, path))
    if dated:
        dated.sort(key=lambda item: item[0])
        latest_token, latest_path = dated[-1]
        if max_age_days is not None:
            # Without a ceiling, this silently returns whatever the most
            # recent matching file is, no matter how old -- fine for most
            # callers, but wrong for a "live, in-game right now" artifact:
            # confirmed live 2026-07-22, WNBA's live_pbp_stats fell back to
            # a 9-day-old file and _advanced_readiness_summary's exists-only
            # check reported it "ready", a false freshness signal. Treat a
            # fallback older than the ceiling as not found at all.
            anchor = requested or central_today_iso()
            try:
                age_days = (date.fromisoformat(anchor) - date.fromisoformat(latest_token)).days
            except (TypeError, ValueError):
                age_days = None
            if age_days is not None and age_days > max_age_days:
                return None
        return latest_path
    return max(candidates, key=lambda item: item.name)


def _nba_live_lens_path(filename: str) -> Path:
    processed_root = nba_processed_path("team_advanced_stats_2026.csv").parents[1]
    return processed_root / "live_lens" / filename


def _wnba_live_lens_path(filename: str) -> Path:
    processed_root = _wnba_repo_artifact_path("recommendations_slate_2026-06-04.json").parents[1]
    return processed_root / "live_lens" / filename


def _resolve_nba_props_predictions_path(context_label: str) -> Path:
    direct = nba_processed_path(f"props_predictions_{context_label}.csv")
    if direct.exists():
        return direct
    return _latest_matching_path(direct.parent, "props_predictions_*.csv", requested_date=context_label) or direct


def _resolve_nba_live_context_path(context_label: str) -> Path:
    direct = _nba_live_lens_path(f"live_lens_projections_{context_label}.jsonl")
    if direct.exists():
        return direct
    return _latest_matching_path(direct.parent, "live_lens_projections_*.jsonl", requested_date=context_label) or direct


_LIVE_PBP_MAX_AGE_DAYS = 1


def _resolve_nba_live_pbp_context_path(context_label: str) -> Path:
    direct = nba_live_snapshot_path(f"live_pbp_stats_{context_label}.jsonl")
    if direct.exists():
        return direct
    return (
        _latest_matching_path(
            direct.parent,
            "live_pbp_stats_*.jsonl",
            requested_date=context_label,
            max_age_days=_LIVE_PBP_MAX_AGE_DAYS,
        )
        or direct
    )


def _resolve_wnba_live_context_path(context_label: str) -> Path:
    direct = _wnba_live_lens_path(f"live_lens_projections_{context_label}.jsonl")
    if direct.exists():
        return direct
    return _latest_matching_path(direct.parent, "live_lens_projections_*.jsonl", requested_date=context_label) or direct


def _resolve_wnba_live_pbp_context_path(context_label: str) -> Path:
    direct = _wnba_repo_artifact_path("live_snapshots", f"live_pbp_stats_{context_label}.jsonl")
    if direct.exists():
        return direct
    return (
        _latest_matching_path(
            direct.parent,
            "live_pbp_stats_*.jsonl",
            requested_date=context_label,
            max_age_days=_LIVE_PBP_MAX_AGE_DAYS,
        )
        or direct
    )


def _resolve_nfl_current_week_path() -> Path:
    direct = nfl_sources.data_path("current_week.json")
    if direct.exists():
        return direct
    fallback = nfl_sources.data_path("source_artifacts", "current_week.json")
    if fallback.exists():
        return fallback
    return direct


def _resolve_nfl_recommendation_context_path(week_value: int, *, season_value: int) -> Path:
    direct = nfl_sources.recommendation_path(week_value, season=season_value)
    if direct.exists():
        return direct
    for candidate in (
        nfl_sources.data_path("source_artifacts", f"upcoming_recs_{season_value}_wk{week_value}.csv"),
        nfl_sources.data_path("source_artifacts", f"upcoming_recs_{season_value}_wk{week_value}_publish.csv"),
    ):
        if candidate.exists():
            return candidate
    return direct


def _resolve_nfl_player_props_path(*, season_value: int, week_value: int) -> Path:
    direct = nfl_sources.data_path(f"oddsapi_player_props_{season_value}_wk{week_value}.csv")
    if direct.exists():
        return direct
    fallback = nfl_sources.data_path("source_artifacts", f"oddsapi_player_props_{season_value}_wk{week_value}.csv")
    if fallback.exists():
        return fallback
    return direct


def _resolve_ncaaf_summary_context_path(week_value: int) -> Path:
    direct = ncaaf_sources.summary_path(week_value)
    if direct.exists():
        return direct
    fallback = ncaaf_sources.default_ncaaf_source_root() / "source_artifacts" / "recommendations_summary" / f"week_{week_value}.json"
    if fallback.exists():
        return fallback
    return direct


def _resolve_ncaaf_summary_index_path() -> Path:
    direct = ncaaf_sources.data_path("recommendations_summary", "index.json")
    if direct.exists():
        return direct
    fallback = ncaaf_sources.default_ncaaf_source_root() / "source_artifacts" / "recommendations_summary" / "index.json"
    if fallback.exists():
        return fallback
    return direct


def _resolve_ncaaf_enhanced_totals_path(*, season_value: int) -> Path:
    root = ncaaf_sources.default_ncaaf_source_root()
    pattern = f"college_football_schedule_{season_value}_predicted_totals_enhanced*.csv"
    for directory in (root / "data", root / "source_artifacts"):
        resolved = _latest_matching_path(directory, pattern)
        if resolved is not None:
            return resolved
    return root / "data" / f"college_football_schedule_{season_value}_predicted_totals_enhanced.csv"


def _resolve_ncaab_live_pbp_context_path(context_label: str) -> Path:
    root = ncaab_sources._source_roots()[0]
    by_date_root = root / "raw_outputs" / "by_date"
    direct = by_date_root / context_label / f"live_features_{context_label}.csv"
    if direct.exists():
        return direct
    return _latest_matching_path(by_date_root, "*/live_features_*.csv", requested_date=context_label) or direct


def _resolve_nhl_scoreboard_context_path(context_label: str) -> Path:
    direct = nhl_scoreboard_snapshot_path(context_label)
    if direct.exists():
        return direct
    games_root = direct.parents[1]
    return _latest_matching_path(games_root, "date=*/scoreboard.csv", requested_date=context_label) or direct


def _resolve_nhl_shift_context_path(context_label: str) -> Path:
    direct = nhl_processed_path(f"shifts_{context_label}.csv")
    if direct.exists():
        return direct
    return _latest_matching_path(direct.parent, "shifts_*.csv", requested_date=context_label) or direct


def _advanced_input_rows_for_sport(sport: dict[str, Any], tracked: set[str]) -> list[dict[str, Any]]:
    advanced_rows: list[dict[str, Any]] = []
    for spec in _advanced_input_specs_for_sport(sport):
        status = _path_status(spec["path"], tracked)
        advanced_rows.append(
            {
                "label": str(spec.get("label") or "Advanced input"),
                "metrics": [str(metric).strip() for metric in (spec.get("metrics") or []) if str(metric).strip()],
                **status,
            }
        )
    return advanced_rows


def _available_advanced_inputs_for_sport(sport: dict[str, Any], tracked: set[str] | None = None) -> list[dict[str, Any]]:
    resolved_tracked = tracked if tracked is not None else _tracked_repo_files()
    rows = _advanced_input_rows_for_sport(sport, resolved_tracked)
    return [row for row in rows if bool(row.get("exists"))]


def _advanced_readiness_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    required_rows = [row for row in rows if bool(row.get("inside_repo"))]
    tracked_rows = [row for row in required_rows if bool(row.get("tracked"))]
    exists_rows = [row for row in required_rows if bool(row.get("exists"))]
    total = len(required_rows)
    tracked_count = len(tracked_rows)
    exists_count = len(exists_rows)
    ratio = float(exists_count / total) if total else (1.0 if rows else 0.0)
    missing = [
        {
            "label": _safe_text(row.get("label"), "Advanced input"),
            "path": _safe_text(row.get("path"), "-"),
            "missing_reason": "missing",
        }
        for row in rows
        if row.get("inside_repo") and not row.get("exists")
    ]
    publish_missing = [
        {
            "label": _safe_text(row.get("label"), "Advanced input"),
            "path": _safe_text(row.get("path"), "-"),
            "missing_reason": "untracked",
        }
        for row in rows
        if row.get("inside_repo") and row.get("exists") and not row.get("tracked")
    ]
    return {
        "required_total": total,
        "tracked_count": tracked_count,
        "exists_count": exists_count,
        "ratio": round(ratio, 3),
        "ready": bool(rows) and not missing,
        "missing_inputs": missing,
        "publish_missing_inputs": publish_missing,
    }


def _advanced_score_adjustment(summary: dict[str, Any]) -> float:
    ratio = float(summary.get("ratio") or 0.0)
    if bool(summary.get("ready")):
        return 6.0
    if ratio >= 0.75:
        return 2.5
    if ratio >= 0.5:
        return 0.0
    if ratio > 0.0:
        return -3.5
    return -7.5


def _readiness_label(summary: dict[str, Any]) -> str:
    if bool(summary.get("ready")):
        return "ready"
    ratio = float(summary.get("ratio") or 0.0)
    if ratio >= 0.5:
        return "partial"
    return "blocked"


def _build_readiness_gate(overview: list[dict[str, Any]], tracked: set[str]) -> dict[str, Any]:
    sport_rows: list[dict[str, Any]] = []
    for sport in overview:
        if not isinstance(sport, dict):
            continue
        slug = _safe_text(sport.get("slug"), "sport").lower()
        active_today = bool(sport.get("active_today"))
        advanced_rows = _advanced_input_rows_for_sport(sport, tracked)
        summary = _advanced_readiness_summary(advanced_rows)
        status = "inactive" if not active_today else _readiness_label(summary)
        sport_rows.append(
            {
                "slug": slug,
                "name": _safe_text(sport.get("name"), slug.upper()),
                "status": status,
                "active_today": active_today,
                "advanced_ready": bool(summary.get("ready")),
                "required_total": int(summary.get("required_total") or 0),
                "tracked_count": int(summary.get("tracked_count") or 0),
                "exists_count": int(summary.get("exists_count") or 0),
                "missing_inputs": summary.get("missing_inputs") or [],
                "publish_missing_inputs": summary.get("publish_missing_inputs") or [],
            }
        )
    ready = [row for row in sport_rows if row.get("status") == "ready"]
    blocked = [row for row in sport_rows if row.get("status") == "blocked"]
    partial = [row for row in sport_rows if row.get("status") == "partial"]
    inactive = [row for row in sport_rows if row.get("status") == "inactive"]
    return {
        "ready": not blocked,
        "ready_sports": [row.get("slug") for row in ready],
        "partial_sports": [row.get("slug") for row in partial],
        "blocked_sports": [row.get("slug") for row in blocked],
        "inactive_sports": [row.get("slug") for row in inactive],
        "sports": sport_rows,
    }


def _advanced_driver_text(rows: list[dict[str, Any]], *, limit_groups: int = 2, limit_metrics: int = 3) -> str:
    if not rows:
        return ""
    groups: list[str] = []
    for row in rows[:limit_groups]:
        metrics = [str(metric).strip() for metric in (row.get("metrics") or []) if str(metric).strip()][:limit_metrics]
        if metrics:
            groups.append(f"{row.get('label')}: {', '.join(metrics)}")
        else:
            groups.append(str(row.get("label") or "Advanced inputs"))
    return "; ".join(groups)


def _advanced_input_specs_for_sport(sport: dict[str, Any]) -> list[dict[str, Any]]:
    slug = str(sport.get("slug") or "").strip().lower()
    context_label = str(sport.get("context_label") or "").strip()
    season = None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label):
        season = int(context_label[:4])

    if slug == "mlb":
        return [
            {
                "label": "Statcast batter and pitcher features",
                "metrics": ["Launch angle", "Exit velocity", "Barrel rate", "Hard-hit rate", "Pitch mix"],
                "path": _mlb_repo_artifact_path("data", "statcast", "features", "player_features_latest.json"),
            },
            {
                "label": "Daily-update simulation contract",
                "metrics": ["Source mode", "Freshness", "Source paths", "Advanced by sport", "HR targets"],
                "path": _repo_root() / "reports" / "daily_update" / "latest" / "unified_daily_update_latest_simulation_contract.json",
            },
            {
                "label": "Live lens and betting-day synthesis",
                "metrics": ["Live projection delta", "Hit pace", "Ladder viability", "Board edge", "Sim confidence"],
                "path": _mlb_repo_artifact_path("data", "live_lens", f"live_lens_report_{context_label.replace('-', '_')}.json") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label) else _mlb_repo_artifact_path("data", "live_lens"),
            },
        ]
    if slug == "nba" and season is not None:
        return [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Defensive rating", "Shot profile", "Rebound environment"],
                "path": nba_processed_path(f"team_advanced_stats_{season}.csv"),
            },
            {
                "label": "Play-by-play live recap",
                "metrics": ["Recent scoring run", "Possession estimate", "Shot mix", "Quarter scoring", "Live sequence pressure"],
                "path": _resolve_nba_live_pbp_context_path(context_label),
            },
            {
                "label": "Player prop model outputs",
                "metrics": ["Usage context", "Minute expectation", "Prop mean", "Edge vs line", "Calibration"],
                "path": _resolve_nba_props_predictions_path(context_label),
            },
            {
                "label": "Live state and pace context",
                "metrics": ["Live pace", "Game state", "In-game line movement", "Board pressure", "Possession context"],
                "path": _resolve_nba_live_context_path(context_label),
            },
        ]
    if slug == "wnba" and season is not None:
        return [
            {
                "label": "Team environment and pace layer",
                "metrics": ["Pace", "Team environment", "Shot volume context", "Possession profile", "Matchup pressure"],
                "path": _wnba_repo_artifact_path(f"recommendations_slate_{context_label}.json"),
            },
            {
                "label": "Play-by-play live recap",
                "metrics": ["Recent scoring run", "Possession estimate", "Shot mix", "Quarter scoring", "Live sequence pressure"],
                "path": _resolve_wnba_live_pbp_context_path(context_label),
            },
            {
                "label": "Player prop model outputs",
                "metrics": ["Usage context", "Minute expectation", "Prop mean", "Edge vs line", "Calibration"],
                "path": _wnba_repo_artifact_path(f"props_recommendations_{context_label}.csv"),
            },
            {
                "label": "Live state mirror",
                "metrics": ["Live pace", "Game state", "Rotation pressure", "In-game projection shift", "Board pressure"],
                "path": _resolve_wnba_live_context_path(context_label),
            },
        ]
    if slug == "nhl" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label):
        return [
            {
                "label": "Game recommendation layer",
                "metrics": ["xG proxy last 10", "Goal pace per 60", "SOG pace per 60", "Pressure flags", "Score effects"],
                "path": nhl_recommendation_path(context_label),
            },
            {
                "label": "Shift and on-ice sequence recap",
                "metrics": ["Shift deployment", "On-ice tempo", "Line matching", "Rest state", "TOI pressure"],
                "path": _resolve_nhl_shift_context_path(context_label),
            },
            {
                "label": "Props recommendation layer",
                "metrics": ["Shot volume", "Goalie saves", "Skater opportunity", "Line edge", "Market depth"],
                "path": nhl_processed_path(f"props_recommendations_{context_label}.csv"),
            },
            {
                "label": "Odds and scoreboard context",
                "metrics": ["Live scoreboard state", "Props lines", "Market change", "Game status", "Book context"],
                "path": _resolve_nhl_scoreboard_context_path(context_label),
            },
        ]
    if slug == "nfl":
        tracked_week = nfl_sources.tracked_week() or {}
        season_value = tracked_week.get("season")
        week_value = tracked_week.get("week")
        if isinstance(season_value, int) and isinstance(week_value, int):
            return [
                {
                    "label": "Weekly recommendation snapshot",
                    "metrics": ["Off EPA", "Def EPA", "Pace", "Pass rate", "Market edge"],
                    "path": _resolve_nfl_recommendation_context_path(week_value, season_value=season_value),
                },
                {
                    "label": "Current week context",
                    "metrics": ["Season", "Week", "Publish state", "Board freshness", "Routing context"],
                    "path": _resolve_nfl_current_week_path(),
                },
                {
                    "label": "Player props mirror",
                    "metrics": ["Passing yards", "Rushing yards", "Receiving yards", "TD market context", "Book coverage"],
                    "path": _resolve_nfl_player_props_path(season_value=season_value, week_value=week_value),
                },
            ]
    if slug == "ncaaf":
        week_match = re.search(r"(?P<season>\d{4})\s+Week\s+(?P<week>\d+)", context_label)
        if week_match:
            week = int(week_match.group("week"))
            season_value = int(week_match.group("season"))
            return [
                {
                    "label": "Weekly recommendation summary",
                    "metrics": ["Model spread", "Model total", "Market edge", "Confidence", "Slate coverage"],
                    "path": _resolve_ncaaf_summary_context_path(week),
                },
                {
                    "label": "Recommendation index",
                    "metrics": ["Week availability", "Fetch health", "Artifact coverage", "Season routing", "Publish context"],
                    "path": _resolve_ncaaf_summary_index_path(),
                },
                {
                    "label": "Enhanced totals export",
                    "metrics": ["Projected total", "Schedule context", "Enhanced totals layer", "Game metadata", "Output freshness"],
                    "path": _resolve_ncaaf_enhanced_totals_path(season_value=season_value),
                },
            ]
    if slug == "ncaab" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label):
        root = ncaab_sources._source_roots()[0]
        return [
            {
                "label": "Recommendations mirror",
                "metrics": ["Spread edge", "Total edge", "Confidence", "Board ranking", "Availability"],
                "path": root / "api" / "recommendations" / f"recommendations_{context_label}.json",
            },
            {
                "label": "Play-by-play derived live recap",
                "metrics": ["Possession estimate", "Points per possession", "Turnover pressure", "Rebound pressure", "Live fetch freshness"],
                "path": _resolve_ncaab_live_pbp_context_path(context_label),
            },
            {
                "label": "Live state mirror",
                "metrics": ["Possession state", "Live total context", "Score pressure", "Game status", "Board timing"],
                "path": root / "api" / "live_state" / f"live_state_{context_label}.json",
            },
            {
                "label": "Pace and live-line context",
                "metrics": ["Pace hi", "Pace low", "Live lines", "Possession rate", "Tempo buckets"],
                "path": root / "api" / "live_lines" / f"live_lines_{context_label}.json",
            },
        ]
    return []


def build_intelligence_status(
    *,
    selected_date: str | None = None,
    force_refresh: bool = False,
    skip_game_hydration: bool = False,
) -> dict[str, Any]:
    if force_refresh:
        _tracked_repo_files.cache_clear()
    overview = build_intelligence_overview(selected_date=selected_date, force_refresh=force_refresh, skip_game_hydration=skip_game_hydration)
    tracked = _tracked_repo_files()
    try:
        refresh_status = load_latest_refresh_status()
    except Exception:
        refresh_status = {}
    sports_status: list[dict[str, Any]] = []
    tracked_ok_count = 0
    tracked_total = 0
    advanced_ready_count = 0
    advanced_total = 0

    for sport in overview:
        artifact_rows: list[dict[str, Any]] = []
        for label, path in _artifact_specs_for_sport(sport):
            status = _path_status(path, tracked)
            if status["inside_repo"]:
                tracked_total += 1
                if status["tracked"]:
                    tracked_ok_count += 1
            artifact_rows.append(
                {
                    "label": label,
                    **status,
                }
            )

        advanced_rows = _advanced_input_rows_for_sport(sport, tracked)
        for status in advanced_rows:
            if status["inside_repo"]:
                advanced_total += 1
                if status["tracked"]:
                    advanced_ready_count += 1

        artifact_exists = any(bool(row.get("exists")) for row in artifact_rows)
        advanced_exists = any(bool(row.get("exists")) for row in advanced_rows)
        active_today = bool(sport.get("active_today")) or artifact_exists or advanced_exists
        data_warnings = [str(item).strip() for item in (sport.get("data_warnings") or []) if str(item).strip()]
        if not artifact_exists and not advanced_exists:
            data_warnings.append("No tracked artifacts or advanced inputs found for this sport context.")
        data_health = "ready" if (artifact_exists or advanced_exists) else "missing"
        _intel_trace(
            "artifact_status",
            sport=_safe_text(sport.get("slug"), "sport").lower(),
            context_label=_safe_text(sport.get("context_label"), _effective_date(selected_date)),
            artifact_exists=artifact_exists,
            advanced_exists=advanced_exists,
            artifact_count=len(artifact_rows),
            advanced_count=len(advanced_rows),
            data_health=data_health,
            artifact_paths=[row.get("path") for row in artifact_rows[:4]],
        )

        sports_status.append(
            {
                "slug": _safe_text(sport.get("slug"), "sport").lower(),
                "name": _safe_text(sport.get("name"), "Sport"),
                "context_label": _safe_text(sport.get("context_label"), _effective_date(selected_date)),
                "data_health": data_health,
                "data_warnings": data_warnings,
                "artifacts": artifact_rows,
                "advanced_inputs": advanced_rows,
                "active_today": active_today,
                "tracked_ready": all(row.get("tracked") for row in artifact_rows if row.get("inside_repo")) if artifact_rows else False,
                "advanced_ready": all(row.get("exists") for row in advanced_rows if row.get("inside_repo")) if advanced_rows else False,
                "advanced_gate": _advanced_readiness_summary(advanced_rows),
            }
        )

    readiness_gate = _build_readiness_gate(overview, tracked)

    daily_update_latest_dir = Path(__file__).resolve().parents[2] / "reports" / "daily_update" / "latest"
    simulation_contract_path = daily_update_latest_dir / "unified_daily_update_latest_simulation_contract.json"
    simulation_contract = None
    if simulation_contract_path.exists():
        simulation_contract = _read_json_payload(simulation_contract_path)
    market_summary = simulation_contract.get("market_summary") if isinstance(simulation_contract, dict) else None
    market_summary_by_sport = simulation_contract.get("market_summary_by_sport") if isinstance(simulation_contract, dict) else None

    return {
        "selected_date": _effective_date(selected_date),
        "sports": sports_status,
        "tracked_summary": {
            "tracked_ok": tracked_ok_count,
            "tracked_total": tracked_total,
        },
        "advanced_summary": {
            "tracked_ok": advanced_ready_count,
            "tracked_total": advanced_total,
        },
        "readiness_gate": readiness_gate,
        "refresh_status": refresh_status,
        "daily_update": {
            **(refresh_status.get("daily_update") if isinstance(refresh_status, dict) and isinstance(refresh_status.get("daily_update"), dict) else {}),
            "simulation_contract_path": str(simulation_contract_path),
            "simulation_contract_exists": simulation_contract is not None,
            "simulation_contract": simulation_contract,
            "market_summary": market_summary,
            "market_summary_by_sport": market_summary_by_sport,
        },
        "local_only": True,
    }


def _read_json_payload(path: Path) -> dict[str, Any] | list[Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _sport_matches_preferences(sport: dict[str, Any], preferences: dict[str, Any]) -> bool:
    requested_sports = preferences.get("requested_sports") or []
    if not requested_sports:
        return True
    return _safe_text(sport.get("slug"), "").lower() in requested_sports


def _requested_date_requires_active_sports(preferences: dict[str, Any]) -> bool:
    requested_date = _safe_text(
        preferences.get("requested_date")
        or preferences.get("selected_date")
        or preferences.get("date"),
        "",
    ).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", requested_date):
        return False
    try:
        return date.fromisoformat(requested_date) >= date.fromisoformat(central_today_iso())
    except Exception:
        return False


def _prop_candidate_from_item(sport: dict[str, Any], item: dict[str, Any], *, surface_key: str, surface_title: str) -> dict[str, Any] | None:
    row = _build_prop_dashboard_row(sport, item, default_surface=surface_title)
    projected_value = _numeric_hint(row.get("projected"))
    line_value = _numeric_hint(row.get("line"))
    # Board audit follow-up, found live 2026-07-31: MLB's HR-targets shelf
    # scrapes narrative writeup/reasons text into a home_rails pregame item
    # (_load_mlb_home_hr_target_items, home.py) that has no real market, no
    # real line, no odds, and no model projection -- just a prose sentence
    # ("His underlying HR-quality profile is running above baseline.") and a
    # team abbreviation stamped into "market". That's not a bettable prop;
    # it leaked onto the Layer 2 board as one, the only "prop" MLB showed at
    # all on a day its real structured props artifact was stale. Same shape
    # as the completeness guard added to _append_game_bet_candidate
    # (home.py) for WNBA's equivalent symptom -- a prop candidate with no
    # real line, no real odds, and no real projection has nothing bettable
    # to show, regardless of which pipeline produced it.
    odds_value = _numeric_hint(row.get("odds"))
    if projected_value is None and line_value is None and odds_value is None:
        return None
    if projected_value is not None and line_value is not None:
        row["score"] = float(row.get("score", 0.0)) + abs(projected_value - line_value) * 3.0
    advanced_signals = _advanced_signals_from_item(item)
    source_summary = _item_source_summary(item)
    detail_text = _safe_text(item.get("detail"), "") or _safe_text(item.get("why_explain"), "") or _safe_text(item.get("shape_summary"), "")
    summary_text = _safe_text(item.get("summary"), "") or _safe_text(item.get("basketball_summary"), "") or _item_reason_summary(item)
    row.update(
        {
            "candidate_type": "prop",
            "surface_key": surface_key,
            "surface_title": surface_title,
            "sport_slug": _safe_text(sport.get("slug"), "sport").lower(),
            "context_label": _safe_text(sport.get("context_label"), ""),
            "game_pk": _safe_int(item.get("game_pk") or item.get("gamePk")),
            "game_id": _safe_text(item.get("game_id") or item.get("gameId") or item.get("game_pk") or item.get("gamePk"), ""),
            "event_id": _safe_text(item.get("event_id") or item.get("eventId") or item.get("game_pk") or item.get("gamePk"), ""),
            "player_name": _safe_text(item.get("player_name"), _safe_text(item.get("name"), "")),
            "player_id": _safe_int(item.get("player_id") or item.get("playerId")),
            "team": _safe_text(item.get("team"), ""),
            "player_team": _safe_text(item.get("team"), ""),
            "team_key": _normalized_market_text(_safe_text(item.get("team"), "")) or None,
            "opponent_team": _safe_text(item.get("opponent_team") or item.get("opponentTeam") or item.get("opponent"), ""),
            "writeup": source_summary,
            "detail": detail_text,
            "summary": summary_text,
            "status_context": _safe_text(item.get("status_context"), ""),
            "status_display": _safe_text(item.get("status_display"), ""),
            "game_state": _safe_text(item.get("game_state"), ""),
            "hero_live_box": item.get("hero_live_box") if isinstance(item.get("hero_live_box"), dict) else None,
            "hero_sim_box": item.get("hero_sim_box") if isinstance(item.get("hero_sim_box"), dict) else None,
            "display_pills": item.get("display_pills") if isinstance(item.get("display_pills"), list) else [],
            "batter_id": _safe_int(item.get("batter_id")),
            "pitcher_id": _safe_int(item.get("pitcher_id")),
            "opponent_pitcher_id": _safe_int(item.get("opponent_pitcher_id")),
            "advanced_signals": advanced_signals,
        }
    )
    _bind_candidate_state(row)
    return row


def _steam_events_path(date_str: str) -> Path:
    return reports_root() / "steam" / f"steam_events_{date_str}.json"


def _load_steam_events_for_date(date_str: str) -> list[dict[str, Any]]:
    payload = read_json_file(_steam_events_path(date_str))
    events = payload.get("events") if isinstance(payload, dict) else None
    return [event for event in events if isinstance(event, dict)] if isinstance(events, list) else []


def _steam_event_current_odds_text(value: Any) -> str:
    odds_value = _american_odds_value(value)
    if odds_value is None:
        return "-"
    return f"+{int(odds_value)}" if odds_value > 0 else str(int(odds_value))


def _soccer_abbr_from_name(team_name: str) -> str:
    tokens = [token for token in str(team_name or "").replace("&", " ").split() if token]
    if not tokens:
        return "-"
    if len(tokens) == 1:
        return tokens[0][:3].upper()
    return "".join(token[0] for token in tokens[:3]).upper()


def _soccer_team_abbr(league: str, team_name: str) -> str:
    # Steam events carry OddsAPI's market-name spelling ("LA Galaxy"), not
    # necessarily the branding directory's exact display name, so an exact
    # team_by_name() miss falls back to the same fuzzy matcher soccer's own
    # cross-source team reconciliation already uses (team_names.py) before
    # giving up and abbreviating the raw text token-by-token.
    from syndicate.features.soccer.sources import all_teams, team_by_name

    text = _safe_text(team_name, "")
    if not text:
        return "-"
    directory_team = team_by_name(league, text)
    if directory_team is None:
        try:
            from syndicate.features.soccer.features.team_names import match_team_name

            names = [_safe_text(team.get("name"), "") for team in all_teams(league)]
            matched_name = match_team_name(text, [name for name in names if name])
        except Exception:
            matched_name = None
        if matched_name:
            directory_team = team_by_name(league, matched_name)
    abbreviation = _safe_text((directory_team or {}).get("abbreviation"), "")
    return abbreviation.upper() if abbreviation else _soccer_abbr_from_name(text)


def _soccer_team_abbr_any_league(selected_date: str, team_name: str) -> str:
    # Steam events carry no league field of their own (see
    # _soccer_steam_matchup_lookup's docstring), so this tries every league
    # active that day rather than requiring the caller to already know which
    # one a given event belongs to.
    from syndicate.features.soccer.sources import active_leagues_for_date

    text = _safe_text(team_name, "")
    if not text:
        return "-"
    try:
        leagues = active_leagues_for_date(selected_date)
    except Exception:
        leagues = []
    for league in leagues:
        abbreviation = _soccer_team_abbr(league, text)
        if abbreviation != _soccer_abbr_from_name(text):
            return abbreviation
    return _soccer_abbr_from_name(text)


_MLB_TEAM_ABBR_BY_NAME: dict[str, str] | None = None


def _mlb_team_abbr_any(team_name: str) -> str:
    # Mirrors _soccer_team_abbr_any_league: MLB game-level steam events
    # (moneyline/spread/total) carry OddsAPI's full club names
    # ("New York Yankees") via event_home/event_away, stamped source-side by
    # odds_refresh_tracking.py -- unlike soccer, this branch used to hand
    # those names straight through unabbreviated, producing a matchup like
    # "New York Yankees @ Chicago White Sox" that can never text-match
    # /api/board/game-chips' abbreviated "NYY @ CWS" chips, so the game
    # rendered as a second, chip-less duplicate card on the board (#160).
    global _MLB_TEAM_ABBR_BY_NAME
    text = _safe_text(team_name, "")
    if not text:
        return "-"
    if _MLB_TEAM_ABBR_BY_NAME is None:
        from syndicate.features.mlb.cards import _MLB_TEAM_META_BY_ABBR

        _MLB_TEAM_ABBR_BY_NAME = {
            str(meta.get("name", "")).strip().lower(): abbr
            for abbr, meta in _MLB_TEAM_META_BY_ABBR.items()
            if meta.get("name")
        }
    abbreviation = _MLB_TEAM_ABBR_BY_NAME.get(text.strip().lower())
    return abbreviation or _soccer_abbr_from_name(text)


def _soccer_steam_matchup_lookup(selected_date: str) -> dict[str, dict[str, str]]:
    """event_id -> {"matchup": "Away @ Home", "league_display": "MLS",
    "game_date": "2026-08-01"} for soccer, built from the raw OddsAPI fetch
    rows (game_odds_current.csv + today's props/<date>.csv per active
    league) -- the only place a steam event's real OddsAPI-hash event_id
    can actually be resolved to team names for events recorded before
    odds_refresh_tracking.py started stamping home_team/away_team
    directly. Cheap: a full day across all active leagues is dozens of
    rows (a single rolling "current odds" file per league), not hundreds.
    Never raises -- game_odds_rows/props_odds_rows already degrade to ()
    on any read failure, matching this whole function's best-effort/
    cosmetic purpose.

    #162: this loop already walks per-league, so the league that resolved
    each event_id is known right here -- stamped alongside matchup so
    _steam_candidates_for_sport can show "MLS"/"La Liga" instead of the
    generic "Soccer" sport label every other steam candidate got before.

    #165 follow-up, confirmed live: every steam candidate's game_date got
    stamped with the board's own requested date (selected_date/
    context_label -- "when this scan ran"), not the individual match's
    real kickoff date. active_leagues_for_date/game_odds_rows/
    props_odds_rows read a rolling odds feed that covers MANY upcoming
    matches across several actual calendar days at once (a single MLS odds
    file mixes this-weekend's whole slate), so every one of those matches
    got mislabeled with the SAME wrong date on the Games strip (e.g. seven
    real Saturday MLS matches all showing "Fri Jul 31").
    #166: first fix attempt cross-referenced a season schedule via fuzzy
    team-name matching -- unnecessary complexity (and, confirmed live,
    genuinely buggy: two real bugs before it worked at all locally, then
    STILL didn't move the needle in production for reasons not fully
    chased down). The raw odds row already carries its own real kickoff
    timestamp directly (confirmed against the actual production CSV:
    "league,event_id,home_team,away_team,commence_time,market,side,line,
    price,book") -- game_odds_rows's row.get("commence_time") is used
    below instead. Simpler, no fuzzy matching, no season-schedule
    dependency, no multi-meeting-in-a-season ambiguity (this IS the
    specific event). props_odds_rows' rows may not carry commence_time;
    those fall back to selected_date same as before this fix, same as
    game_odds_rows rows before it existed.
    """
    try:
        from syndicate.features.soccer.sources import active_leagues_for_date, game_odds_rows, league_display_name, props_odds_rows
    except Exception:
        return {}
    lookup: dict[str, dict[str, str]] = {}
    try:
        leagues = active_leagues_for_date(selected_date)
    except Exception:
        leagues = []
    for league in leagues:
        rows: tuple[dict[str, str], ...] = ()
        try:
            rows = (*game_odds_rows(league), *props_odds_rows(league, selected_date))
        except Exception:
            continue
        for row in rows:
            event_id = _safe_text(row.get("event_id"), "")
            if not event_id or event_id in lookup:
                continue
            home = _safe_text(row.get("home_team"), "")
            away = _safe_text(row.get("away_team"), "")
            if home or away:
                away_abbr = _soccer_team_abbr(league, away) if away else "-"
                home_abbr = _soccer_team_abbr(league, home) if home else "-"
                entry = {"matchup": f"{away_abbr} @ {home_abbr}", "league_display": league_display_name(league)}
                kickoff_date = _safe_text(row.get("commence_time"), "")[:10]
                if kickoff_date:
                    entry["game_date"] = kickoff_date
                lookup[event_id] = entry
    return lookup


def _steam_candidates_for_sport(sport: dict[str, Any]) -> list[dict[str, Any]]:
    """Board candidates built directly from detected steam (sharp/steam line)
    moves, per the user's explicit direction: steam should be a real,
    filterable row TYPE on the main opportunity board -- "call these out as
    steam moves." Originally added alongside a separate top-strip rail
    (`/api/board/steam`, pregame-only by product decision) which the user
    then had removed once this board integration was confirmed working, so
    this function is now the sole board-facing consumer of steam detection.

    Detection itself (_steam_signal, odds_refresh_tracking.py) already
    covers live AND pregame with real per-event granularity via
    capture_phase ("live"/"closing"/"ramp"/"drift") and a plain is_live
    bool. Every steam event for this sport becomes a real candidate here,
    tagged with its own lane so the existing LIVE/PREGAME state filter, and
    the steam-only filter, both work on it exactly like any other candidate.
    """
    sport_slug = _safe_text(sport.get("slug"), "").lower()
    if not sport_slug:
        return []
    selected_date = _safe_text(sport.get("context_label"), "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", selected_date):
        return []
    events = _load_steam_events_for_date(selected_date)
    if not events:
        return []

    # Best-effort matchup text -- the raw lifecycle event itself carried no
    # matchup field at all before #137's follow-up (odds_refresh_tracking.py
    # now stamps home_team/away_team directly onto new events for sports
    # whose CSV rows have those columns), so older events and sports without
    # them still need a lookup. Not required for correctness (the
    # identity-dedup fix above no longer depends on it), just avoids a
    # universal "-" on every steam row.
    matchup_by_game_id: dict[str, str] = {}
    # away-abbr|home-abbr -> game_key, so a steam event that only carries
    # full team names (no game_id of its own) can still resolve today's
    # real game_id once those names are abbreviated below -- without this,
    # the candidate kept game_id empty even after the abbreviation fix,
    # which still left it in a matchup-text-only mini-card group that
    # /api/board/game-chips (id-keyed first) couldn't match (#160).
    game_id_by_team_abbrs: dict[str, str] = {}
    # Same "actual" concept as _append_game_bet_candidate's game-level
    # fallback (home.py's _game_current_combined_score) -- the current
    # combined score, the one signal meaningful across every game-level
    # market type (moneyline/spread/total). Steam candidates had no
    # "actual" field at all before this (unlike props, which already
    # carry one from odds tracking), so every game-level steam candidate
    # serialized it as a raw None instead of the "-" placeholder every
    # other unresolvable field on this board uses.
    actual_by_game_id: dict[str, float] = {}
    # Board-alignment audit, found live 2026-08-01 against a real live WNBA
    # game: actual_by_game_id's combined score is right for "total" (the
    # one market_key in _GAME_SIDE_MARKETS genuinely comparable to it) but
    # was ALSO being shown for "moneyline"/"spread" steam candidates --
    # every game-side steam candidate for the same live game showed the
    # identical combined number regardless of which side/market it was
    # actually about. Tracked separately so moneyline/spread candidates can
    # show the real away-home scoreline instead (see the render site
    # below).
    scoreline_by_game_id: dict[str, str] = {}
    # #162: soccer's game dicts (soccer/cards.py) stamp league_display
    # ("MLS", "La Liga", ...) directly -- carried through so steam
    # candidates can show the real league instead of the generic "Soccer"
    # sport label every other candidate type on this board already fixed.
    league_display_by_game_id: dict[str, str] = {}
    # #165 follow-up: soccer steam candidates otherwise got game_date
    # stamped with `selected_date` (the board's own requested date, i.e.
    # "when this scan ran") -- wrong for any match not actually happening
    # that day, since the raw odds feed a single scan reads covers many
    # upcoming matches across several real calendar days at once. Real
    # per-event kickoff dates (resolved via the season schedule, see
    # _soccer_steam_matchup_lookup) go here.
    game_date_by_game_id: dict[str, str] = {}
    for game in sport.get("dashboard_games") if isinstance(sport.get("dashboard_games"), list) else []:
        if not isinstance(game, dict):
            continue
        game_key = _safe_text(game.get("gamePk") or game.get("game_id") or game.get("event_id"), "")
        if not game_key:
            continue
        away = game.get("away") if isinstance(game.get("away"), dict) else {}
        home = game.get("home") if isinstance(game.get("home"), dict) else {}
        away_label = _safe_text(away.get("abbr") or away.get("name"), "") or _safe_text(game.get("away_label"), "")
        home_label = _safe_text(home.get("abbr") or home.get("name"), "") or _safe_text(game.get("home_label"), "")
        if away_label or home_label:
            matchup_by_game_id[game_key] = f"{away_label or '-'} @ {home_label or '-'}"
        league_display_val = _safe_text(game.get("league_display"), "")
        if league_display_val:
            league_display_by_game_id[game_key] = league_display_val
        game_date_val = _safe_text(game.get("game_date") or game.get("scheduled_start_utc"), "")[:10]
        if game_date_val:
            game_date_by_game_id[game_key] = game_date_val
        away_abbr_val = _safe_text(away.get("abbr"), "").upper()
        home_abbr_val = _safe_text(home.get("abbr"), "").upper()
        if away_abbr_val and home_abbr_val:
            game_id_by_team_abbrs[f"{away_abbr_val}|{home_abbr_val}"] = game_key
        live_state = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
        away_score = _numeric_hint(away.get("score"))
        if away_score is None:
            away_score = _numeric_hint(live_state.get("away_pts"))
        if away_score is None:
            away_score = _numeric_hint(game.get("away_score"))
        home_score = _numeric_hint(home.get("score"))
        if home_score is None:
            home_score = _numeric_hint(live_state.get("home_pts"))
        if home_score is None:
            home_score = _numeric_hint(game.get("home_score"))
        if away_score is not None and home_score is not None:
            actual_by_game_id[game_key] = away_score + home_score
            scoreline_by_game_id[game_key] = f"{away_score:.0f}-{home_score:.0f}"
    # Confirmed live: soccer's steam moves showed a real, consistent
    # OddsAPI-hash game_id but every one still landed on "-" -- dashboard_games
    # can't resolve it (single-league-curated, _resolve_league picks exactly
    # one league/day) AND is keyed by the sim's own ESPN-numeric event_id, a
    # completely different id space from OddsAPI's hash (same mismatch
    # documented in soccer/market_board.py). This is the one sport where the
    # authoritative event_id -> team-name join lives in its own raw fetch
    # rows, so it gets its own read-time lookup for events recorded before
    # the source-side stamp above existed.
    if sport_slug == "soccer":
        for event_id, lookup_entry in _soccer_steam_matchup_lookup(selected_date).items():
            matchup_by_game_id.setdefault(event_id, lookup_entry.get("matchup", "-"))
            league_display_val = lookup_entry.get("league_display")
            if league_display_val:
                league_display_by_game_id.setdefault(event_id, league_display_val)
            game_date_val = lookup_entry.get("game_date")
            if game_date_val:
                game_date_by_game_id.setdefault(event_id, game_date_val)

    # Confirmed live: MLB steam candidates built from hitter/pitcher prop
    # rows (_flatten_mlb_props) had NO game_id at all -- unlike soccer's raw
    # rows, those rows carry no event_id/game_id/team column whatsoever
    # (odds_refresh_tracking.py's _canonical_event_id/_market_lifecycle_event
    # have nothing to read), so every one of these candidates landed under
    # the same shared "mlb|-" grouping key with no resolvable matchup. The
    # per-game roster snapshots (mlb_player_game_lookup_for_date,
    # hr_targets.py -- already used the same way for HR-target matchups) are
    # the only place a game_pk can be joined to one of these events, via the
    # player's own name; the resolved game_pk is dashboard_games' own key,
    # so it flows straight into the matchup_by_game_id lookup above with no
    # separate join needed.
    mlb_game_pk_by_player: dict[str, int] = {}
    if sport_slug == "mlb":
        from syndicate.features.mlb.hr_targets import mlb_normalize_player_name, mlb_player_game_lookup_for_date

        mlb_game_pk_by_player = mlb_player_game_lookup_for_date(selected_date)

    candidates: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str, str, str, str]] = set()
    for event in events:
        if _safe_text(event.get("sport"), "").lower() != sport_slug:
            continue
        steam = event.get("steam") if isinstance(event.get("steam"), dict) else {}
        if not steam:
            continue
        capture_phase = _safe_text(steam.get("capture_phase") or event.get("capture_phase"), "")
        is_live = bool(event.get("is_live")) or capture_phase == "live"
        lane = "live" if is_live else "pregame"
        market_type = _safe_text(event.get("market_type"), "")
        market_key = _market_key_from_text(market_type, allow_fallback=True)
        market_label = _market_label(market_key) if market_key else (market_type.replace("_", " ").title() or "Market")
        selection = _safe_text(event.get("selection"), "")
        # player_name is case-inconsistent at the source ("willy adames") --
        # holds a real team name for game-level markets too (populated
        # upstream via normalized_entry.get("entity")/row.get("entity"),
        # _market_lifecycle_event, odds_refresh_tracking.py).
        player_name = _safe_text(event.get("player_name"), "").strip().title()
        subject = player_name or selection or market_label
        current_line = _numeric_hint(event.get("line"))
        current_price = _numeric_hint(event.get("price"))
        previous_line = _numeric_hint(steam.get("previous_line"))
        previous_price = _numeric_hint(steam.get("previous_odds"))
        line_delta = _numeric_hint(steam.get("line_delta"))
        odds_delta = _numeric_hint(steam.get("odds_delta"))
        implied_prob = _numeric_hint(event.get("implied_prob"))
        game_id = _safe_text(event.get("game_id"), "")
        if not game_id and sport_slug == "mlb" and player_name:
            resolved_game_pk = mlb_game_pk_by_player.get(mlb_normalize_player_name(player_name))
            if resolved_game_pk is not None:
                game_id = str(resolved_game_pk)
        timestamp = _safe_text(event.get("timestamp"), "")
        # Prefer the event's own stamped team names (new events, per the
        # odds_refresh_tracking.py source-side fix) over the lookup tables
        # built once above -- most direct, no join needed.
        event_home = _safe_text(event.get("home_team"), "")
        event_away = _safe_text(event.get("away_team"), "")
        # Board audit follow-up, 2026-07-31: a team-level (moneyline/spread)
        # steam candidate had no counterpart in the prop/steam merge above
        # -- its player_name is deliberately nulled just below (a team-total
        # steam move must not masquerade as a "player prop"), so it carried
        # no comparable identity for _game_side_merge_dedup_key to resolve
        # against a "game"-type Moneyline/Spread candidate's own resolved
        # team abbreviation (home.py's _game_team_label, which prefers
        # payload["abbr"]). Resolved here, once, using the SAME abbreviation
        # lookup already computed below for matchup_text, rather than a
        # second resolution pass -- only for moneyline/spread (a Total bet
        # has no team side; deliberately not stamped for it, since a
        # generic "-" team value would be unsafe to merge on).
        team_side_value: str | None = None
        if event_home or event_away:
            if sport_slug == "soccer":
                # Steam events carry OddsAPI's full team names -- convert to
                # the same abbreviation soccer/cards.py hands the Layer 2
                # mini game-card strip, so this candidate type shows a
                # tricode like every other soccer card instead of a full
                # club name, and (when it resolves the same code) can even
                # id-less-match a live game-chip's own abbreviated matchup.
                away_text = _soccer_team_abbr_any_league(selected_date, event_away) if event_away else "-"
                home_text = _soccer_team_abbr_any_league(selected_date, event_home) if event_home else "-"
            elif sport_slug == "mlb":
                # Same problem as soccer above, for MLB's own game-level
                # (moneyline/spread/total) steam candidates: OddsAPI's full
                # club names ("New York Yankees") were passed straight
                # through, so this matchup could never text-match a
                # game-chip's abbreviated "NYY @ CWS" -- and because these
                # rows also carry no game_id (the player-name game_pk
                # lookup above only applies to prop events), the candidate
                # fell back to a matchup-keyed mini-card group that showed
                # the full names as a second, duplicate "Games" strip card
                # for the same live game (#160).
                away_text = _mlb_team_abbr_any(event_away) if event_away else "-"
                home_text = _mlb_team_abbr_any(event_home) if event_home else "-"
                if not game_id:
                    game_id = game_id_by_team_abbrs.get(f"{away_text}|{home_text}", "")
            else:
                away_text, home_text = event_away or "-", event_home or "-"
            matchup_text = f"{away_text} @ {home_text}"
            if market_key in ("moneyline", "spread") and player_name:
                if event_home and player_name.strip().lower() == event_home.strip().lower():
                    team_side_value = home_text
                elif event_away and player_name.strip().lower() == event_away.strip().lower():
                    team_side_value = away_text
        else:
            matchup_text = matchup_by_game_id.get(game_id, "-")
        # player_name and selection were previously OR'd into a single slot
        # -- two different players sharing the same selection ("Over")
        # collapsed into one, silently dropping one player's real steam
        # event before it ever became a candidate.
        dedupe_key = (sport_slug, game_id, market_type, player_name, selection, timestamp)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        # #137 follow-up, confirmed live: candidates were generating and
        # surviving scoring (INTEL_TRACE showed steam counts intact through
        # candidate_scoring) but never reaching the final board. Root cause:
        # _collect_candidates' identity-dedup tuple is (candidate_type,
        # sport_slug, matchup, market, pick[, game_identity]) -- matchup was
        # always "-" here (no per-game text resolvable from a raw lifecycle
        # event) and pick was a bare "Over 4.5" with no subject, so any two
        # DIFFERENT players/teams sharing the same market+line+selection
        # (common -- "Over 4.5" recurs constantly) collided on identity and
        # all but the highest-scored one were silently dropped as
        # duplicates, even when game_identity (from game_id) also differed.
        # Baking subject into pick makes the tuple genuinely unique per
        # steam event without needing a real matchup string.
        pick_text = (
            f"{subject} {selection} {current_line:.1f}".strip()
            if selection and current_line is not None
            else f"{subject} {selection}".strip() if selection else f"{subject} steam move"
        )
        odds_text = _steam_event_current_odds_text(current_price)
        line_direction = "up" if (line_delta or 0.0) > 0 else "down" if (line_delta or 0.0) < 0 else "flat"
        price_direction = "up" if (odds_delta or 0.0) > 0 else "down" if (odds_delta or 0.0) < 0 else "flat"
        move_bits = []
        if line_delta:
            move_bits.append(f"line moved {line_delta:+.1f}")
        if odds_delta:
            move_bits.append(f"price moved {odds_delta:+.0f}")
        move_text = " and ".join(move_bits) if move_bits else "odds moved sharply"

        candidates.append(
            {
                "candidate_type": "steam",
                # #162: prefer the resolved league ("MLS", "La Liga") over
                # the generic sport family name for soccer -- see
                # league_display_by_game_id above.
                "sport": league_display_by_game_id.get(game_id) or _safe_text(sport.get("name"), sport_slug.upper()),
                "sport_slug": sport_slug,
                "surface_key": lane,
                "surface_title": "Steam moves",
                "name": f"{subject} {market_label} steam move".strip(),
                # Only set on a genuine player prop -- market_key already
                # canonicalizes market_type into _GAME_SIDE_MARKETS'
                # vocabulary for team/game-level markets (moneyline/spread/
                # total), and the frontend's market-family filter treats
                # any candidate with a truthy player_name as a "prop"
                # (matchesClientFilters, intelligence.html) regardless of
                # candidate_type -- a team-total steam move would otherwise
                # wrongly show up under "Player props" and disappear from
                # "Game markets".
                "player_name": (player_name or None) if market_key not in _GAME_SIDE_MARKETS else None,
                # Board audit follow-up: same field name home.py's
                # _game_team_label stamps on a "game"-type Moneyline/Spread
                # candidate (which also prefers the resolved abbreviation),
                # so _game_side_merge_dedup_key can compare the two without
                # a second, disagreeing team-identity convention.
                "team": team_side_value,
                "market": f"{market_label} · Steam",
                "market_key": market_key,
                "pick": pick_text,
                "selection": pick_text,
                "matchup": matchup_text,
                "game_id": game_id,
                "event_id": game_id,
                "game_pk": _safe_int(game_id),
                "context_label": selected_date,
                # #165 follow-up: game_date_by_game_id carries each soccer
                # match's real per-event kickoff date (resolved via the
                # season schedule) when available -- context_label alone is
                # "the date this scan ran for," not this specific match's
                # real date, and the frontend's Games-strip date badge
                # (intelligence.html's fallbackDate) reads game_date/
                # source_board_date before falling back to context_label.
                "game_date": game_date_by_game_id.get(game_id) or selected_date,
                "source_board_date": game_date_by_game_id.get(game_id) or selected_date,
                "line": f"{current_line:.1f}" if current_line is not None else "-",
                "odds": odds_text,
                "projected": "-",
                "confidence": f"{implied_prob * 100.0:.1f}%" if implied_prob is not None else "-",
                "model_probability": implied_prob,
                "edge": "-",
                "actual": (
                    f"{actual_by_game_id[game_id]:.1f}"
                    if market_key == "total" and game_id in actual_by_game_id
                    else scoreline_by_game_id.get(game_id, "-")
                    if market_key in _GAME_SIDE_MARKETS
                    else "-"
                ),
                "is_live": is_live,
                "lane": lane,
                "line_odds_movement": {
                    "opening_line": previous_line,
                    "latest_line": current_line,
                    "line_delta": line_delta,
                    "line_direction": line_direction,
                    "opening_price": previous_price,
                    "latest_price": current_price,
                    "price_delta": odds_delta,
                    "price_direction": price_direction,
                },
                "steam": {
                    "capture_phase": capture_phase or None,
                    "window_seconds": steam.get("window_seconds"),
                    "line_delta": line_delta,
                    "odds_delta": odds_delta,
                },
                "timestamp": timestamp or None,
                "last_updated": timestamp or None,
                "source": _safe_text(event.get("source"), "") or None,
                "score": (abs(line_delta or 0.0) * 20.0) + (abs(odds_delta or 0.0) * 0.5),
                "href": f"/{sport_slug}/cards?date={selected_date}",
                "href_label": "Open board",
                "writeup": f"Steam move: {market_label} for {subject} -- {move_text}.",
                "display_pills": [
                    pill
                    for pill in (
                        f"Line {previous_line:.1f} → {current_line:.1f}"
                        if previous_line is not None and current_line is not None and previous_line != current_line
                        else "",
                        f"Odds {int(previous_price)} → {int(current_price)}"
                        if previous_price is not None and current_price is not None and previous_price != current_price
                        else "",
                        "Live" if is_live else capture_phase.title() if capture_phase else "Pregame",
                    )
                    if pill
                ],
            }
        )
    return candidates


def _mlb_home_run_candidates_from_artifact(sport: dict[str, Any]) -> list[dict[str, Any]]:
    if _safe_text(sport.get("slug"), "").lower() != "mlb":
        return []
    selected_date = _safe_text(sport.get("context_label"), "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", selected_date):
        return []
    summary = mlb_load_json_file(mlb_daily_artifact_path(selected_date, suffix="_hr_targets"))
    rows = summary.get("rows") if isinstance((summary or {}).get("rows"), list) else []
    candidates: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:10], start=1):
        if not isinstance(row, dict):
            continue
        hr_probability = _numeric_hint(row.get("p_hr_1plus"))
        support_score = _numeric_hint(row.get("hr_support_raw_score") or row.get("hr_support_score"))
        player_name = _safe_text(row.get("player_name"), "Unknown hitter")
        reasons = [str(item).strip() for item in (row.get("hr_target_reasons") or []) if str(item).strip()]
        writeup = _safe_text(row.get("hr_target_summary"), "") or " ".join(reasons[:2])
        display_pills: list[str] = []
        if hr_probability is not None:
            display_pills.append(f"HR Prob {hr_probability * 100.0:.1f}%")
        if support_score is not None:
            display_pills.append(f"Support {support_score:.0f}")
        lineup_order = _safe_int(row.get("lineup_order"))
        if lineup_order is not None:
            display_pills.append(f"Lineup {lineup_order}")
        advanced_signals = [
            {
                "key": "batter_statcast_hr_mult",
                "label": _humanize_signal_key("batter_statcast_hr_mult"),
                "value": round(float(row.get("batter_platoon_hr_mult")), 3),
            }
            for _ in [0]
            if _numeric_hint(row.get("batter_platoon_hr_mult")) is not None
        ]
        if _numeric_hint(row.get("pitcher_platoon_hr_mult")) is not None:
            advanced_signals.append(
                {
                    "key": "pitcher_statcast_hr_mult",
                    "label": _humanize_signal_key("pitcher_statcast_hr_mult"),
                    "value": round(float(_numeric_hint(row.get("pitcher_platoon_hr_mult")) or 0.0), 3),
                }
            )
        score = float(hr_probability or 0.0) * 100.0 + float(support_score or 0.0) + max(0.0, 12.0 - float(index))
        candidates.append(
            {
                "candidate_type": "prop",
                "sport": _safe_text(sport.get("name"), "MLB"),
                "sport_slug": "mlb",
                "surface_key": "pregame",
                "surface_title": "HR targets",
                "name": player_name,
                "market": "Home Runs",
                "market_key": "home_runs",
                "pick": "Over 0.5",
                "matchup": _safe_text(row.get("matchup"), "-"),
                "team": _safe_text(row.get("team"), "-"),
                "team_key": _safe_text(row.get("team"), "").lower() or None,
                "player_team": _safe_text(row.get("team"), "-"),
                # Without these, this candidate type has no id at all, so the
                # Layer 2 mini game-card strip's grouping falls back to a
                # sport+matchup-text key (intelligence.html's gameKey()) that
                # never matches the id-keyed group every other MLB candidate
                # type produces for the same real game -- confirmed live as
                # a duplicate "Team A @ Team B, N opportunities" fallback
                # card sitting next to the real, chip-hydrated score card.
                "game_pk": _safe_int(row.get("gamePk") or row.get("game_pk")),
                "game_id": _safe_text(row.get("gamePk") or row.get("game_pk"), ""),
                "event_id": _safe_text(row.get("gamePk") or row.get("game_pk"), ""),
                "line": "0.5",
                "odds": "-",
                "projected": "-",
                "confidence": f"{hr_probability * 100.0:.1f}%" if hr_probability is not None else "-",
                # These candidates have no book odds/line to project against
                # (the HR board isn't priced) -- their real strength signal
                # is the model's own hit probability. normalize_candidate's
                # projection scan never looked at hr_probability, only at
                # model_probability, so with odds/projected both "-" every
                # HR-target candidate this function has ever produced was
                # pruned at classification as missing_projection_or_odds --
                # confirmed: the feature has never actually reached the
                # board. model_probability is exactly the right slot for a
                # model-computed hit probability, not a workaround.
                "model_probability": hr_probability,
                "edge": "-",
                "actual": "-",
                "score": score,
                "href": f"/mlb/hr-targets?date={selected_date}",
                "href_label": "Open HR board",
                "writeup": writeup,
                "display_pills": display_pills,
                "advanced_signals": advanced_signals,
                "batter_id": _safe_int(row.get("batter_id")),
                "opponent_pitcher_id": _safe_int(row.get("opponent_pitcher_id")),
                "lineup_order": lineup_order,
                "hr_support_score": support_score,
                "hr_probability": hr_probability,
            }
        )
    return candidates


def _mlb_top_props_rows_from_artifact(selected_date: str) -> list[dict[str, Any]]:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", selected_date):
        return []
    top_props = mlb_load_json_file(mlb_daily_top_props_path(selected_date))
    groups = top_props.get("groups") if isinstance((top_props or {}).get("groups"), dict) else {}
    rows: list[dict[str, Any]] = []
    for group in groups.values():
        if not isinstance(group, dict):
            continue
        sections = group.get("sections") if isinstance(group.get("sections"), list) else []
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_rows = section.get("rows") if isinstance(section.get("rows"), list) else []
            for row in section_rows:
                if isinstance(row, dict):
                    rows.append(row)
    return rows


def _mlb_prop_candidate_from_artifact_row(
    sport: dict[str, Any],
    row: dict[str, Any],
    *,
    selected_date: str,
    pitcher_market_rows: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    player_name = _safe_text(row.get("ownerName") or row.get("playerName"), "")
    if not player_name:
        return None
    market_key = _market_key_from_text(row.get("stat") or row.get("statLabel"), allow_fallback=True)
    if not market_key:
        return None

    normalized_name = _normalized_market_text(player_name)
    snapshot_player = pitcher_market_rows.get(normalized_name) if isinstance(pitcher_market_rows, dict) else None
    snapshot_market = snapshot_player.get(market_key) if isinstance((snapshot_player or {}).get(market_key), dict) else {}
    line_value = _numeric_hint(snapshot_market.get("line"))
    if line_value is None:
        line_value = _numeric_hint(row.get("marketLine") or row.get("line"))
    mean_value = _numeric_hint(row.get("mean"))
    sim_prob = _numeric_hint(row.get("simProb"))
    raw_edge = _numeric_hint(row.get("rawEdge"))
    selection_label = _safe_text(row.get("selectionLabel"), "Over") or "Over"
    selection_direction = 1 if selection_label.lower() == "over" else -1 if selection_label.lower() == "under" else 0
    odds_text = _safe_text(
        snapshot_market.get("over_odds") if selection_direction >= 0 else snapshot_market.get("under_odds"),
        "",
    )
    if not odds_text:
        odds_value = _american_odds_value(row.get("odds"))
        if odds_value is not None:
            odds_text = f"+{int(odds_value)}" if odds_value > 0 else str(int(odds_value))
    matchup = _safe_text(row.get("matchup"), "-")
    market_label = _safe_text(row.get("statLabel"), "") or _market_label(market_key)
    pick = f"{selection_label} {line_value:.1f}" if line_value is not None else selection_label
    projected_text = f"{mean_value:.1f}" if mean_value is not None else "-"
    confidence_text = f"{sim_prob * 100.0:.1f}%" if sim_prob is not None else "-"
    edge_text = f"{raw_edge * 100.0:.1f}%" if raw_edge is not None else "-"
    detail_bits = []
    if mean_value is not None and line_value is not None:
        detail_bits.append(f"Projection {mean_value:.1f} versus line {line_value:.1f}")
    if sim_prob is not None:
        detail_bits.append(f"Sim win probability {sim_prob * 100.0:.1f}%")
    if raw_edge is not None:
        detail_bits.append(f"Raw edge {raw_edge * 100.0:.1f}%")
    score = float(sim_prob or 0.0) * 70.0 + max(0.0, float(raw_edge or 0.0) * 50.0)
    rank_value = _safe_int(row.get("rank"))
    if rank_value is not None:
        score += max(0.0, 8.0 - float(rank_value))
    return {
        "candidate_type": "prop",
        "sport": _safe_text(sport.get("name"), "MLB"),
        "sport_slug": "mlb",
        "surface_key": "pregame",
        "surface_title": "Top props artifact",
        "name": f"{player_name} {selection_label} {line_value:.1f} {market_label}" if line_value is not None else f"{player_name} {selection_label} {market_label}",
        "market": f"Pitcher {market_label}" if _safe_text(row.get("group"), "").lower() == "pitcher" else market_label,
        "market_key": market_key,
        "pick": pick,
        "matchup": matchup,
        "team": _safe_text(row.get("team"), "-"),
        "team_key": _normalized_market_text(_safe_text(row.get("team"), "")) or None,
        "player_team": _safe_text(row.get("team"), "-"),
        "game_pk": _safe_int(row.get("gamePk") or row.get("game_pk")),
        "game_id": _safe_text(row.get("gamePk") or row.get("game_pk"), ""),
        "event_id": _safe_text(row.get("gamePk") or row.get("game_pk"), ""),
        "opponent_team": _safe_text(row.get("opponent"), ""),
        "opponent_team_key": _normalized_market_text(_safe_text(row.get("opponent"), "")) or None,
        "line": f"{line_value:.1f}" if line_value is not None else "-",
        "odds": odds_text or "-",
        "projected": projected_text,
        "confidence": confidence_text,
        "edge": edge_text,
        # Baseline placeholder, never left absent -- _mlb_hydrate_live_
        # prop_projection overwrites this with a real value once the game
        # is live and a matching live-lens row exists; without this default,
        # a candidate whose game hasn't gone live yet (or hasn't been
        # hydrated in this cycle) serialized "actual" as a raw None instead
        # of the "-" placeholder every other unresolvable field uses.
        "actual": "-",
        "score": score,
        "href": f"/mlb/cards?date={selected_date}",
        "href_label": "Open board",
        "writeup": ". ".join(detail_bits) if detail_bits else f"Artifact-backed {market_label.lower()} view for {player_name}.",
        "display_pills": [
            pill
            for pill in (
                f"Proj {projected_text}" if projected_text != "-" else "",
                f"Line {line_value:.1f}" if line_value is not None else "",
                f"Sim% {confidence_text}" if confidence_text != "-" else "",
            )
            if pill
        ],
        "owner_id": _safe_int(row.get("ownerId")),
        "selection_direction": selection_direction,
    }


def _mlb_market_prop_candidates_from_artifact(sport: dict[str, Any], preferences: dict[str, Any]) -> list[dict[str, Any]]:
    if _safe_text(sport.get("slug"), "").lower() != "mlb":
        return []
    selected_date = _safe_text(sport.get("context_label"), "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", selected_date):
        return []
    requested_markets = {
        str(item).strip().lower()
        for item in (preferences.get("requested_markets") or [])
        if str(item).strip()
    }
    requested_markets.discard("home_runs")
    if not requested_markets:
        return []

    rows = _mlb_top_props_rows_from_artifact(selected_date)
    pitcher_snapshot = mlb_load_json_file(mlb_daily_snapshot_oddsapi_pitcher_props_path(selected_date))
    pitcher_market_rows = pitcher_snapshot.get("pitcher_props") if isinstance((pitcher_snapshot or {}).get("pitcher_props"), dict) else {}
    candidates: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate = _mlb_prop_candidate_from_artifact_row(
            sport,
            row,
            selected_date=selected_date,
            pitcher_market_rows=pitcher_market_rows,
        )
        if not isinstance(candidate, Mapping):
            continue
        market_key = _candidate_market_key(candidate)
        if market_key not in requested_markets:
            continue
        dedupe_key = (
            _normalized_market_text(_safe_text(row.get("ownerName") or row.get("playerName"), "")),
            _safe_text(market_key, ""),
            _safe_text(candidate.get("pick"), ""),
        )
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        candidates.append(candidate)
    return candidates


def _mlb_subject_prop_candidates_from_artifact(
    sport: dict[str, Any],
    *,
    question: str,
    preferences: dict[str, Any],
) -> list[dict[str, Any]]:
    if _safe_text(sport.get("slug"), "").lower() != "mlb":
        return []
    selected_date = _safe_text(sport.get("context_label"), "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", selected_date):
        return []
    normalized_question = _normalized_market_text(question)
    if not normalized_question:
        return []
    requested_markets = {
        str(item).strip().lower()
        for item in (preferences.get("requested_markets") or [])
        if str(item).strip()
    }
    rows = _mlb_top_props_rows_from_artifact(selected_date)
    pitcher_snapshot = mlb_load_json_file(mlb_daily_snapshot_oddsapi_pitcher_props_path(selected_date))
    pitcher_market_rows = pitcher_snapshot.get("pitcher_props") if isinstance((pitcher_snapshot or {}).get("pitcher_props"), dict) else {}
    candidates: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        player_name = _safe_text(row.get("ownerName") or row.get("playerName"), "")
        normalized_name = _normalized_market_text(player_name)
        if not normalized_name:
            continue
        if not re.search(rf"(?<![a-z0-9]){re.escape(normalized_name)}(?![a-z0-9])", normalized_question):
            continue
        market_key = _market_key_from_text(row.get("stat") or row.get("statLabel"), allow_fallback=True)
        if not market_key:
            continue
        if requested_markets and market_key not in requested_markets:
            continue
        dedupe_key = (normalized_name, market_key)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        candidate = _mlb_prop_candidate_from_artifact_row(
            sport,
            row,
            selected_date=selected_date,
            pitcher_market_rows=pitcher_market_rows,
        )
        if isinstance(candidate, Mapping):
            candidates.append(candidate)
    return candidates


def _mlb_pregame_mean_by_player_market(selected_date: str) -> dict[tuple[str, str, int | None], float]:
    """Normalized player name + market key (+ game_pk) -> pregame sim mean,
    read from the same daily_top_props artifact _mlb_prop_candidate_from_
    artifact_row already sources its own "projected" from (row.get("mean")).

    _mlb_live_lens_prop_candidates_from_artifact's own rows (trackedProps/
    props on the live-lens report) carry no pregame projection field at all
    -- only a live one -- so this is the one place a genuine pregame value
    can still be attached to a live-lens-sourced candidate, via a join on
    the player+market (+game) rather than a shared row shape.
    """
    lookup: dict[tuple[str, str, int | None], float] = {}
    for row in _mlb_top_props_rows_from_artifact(selected_date):
        player_name = _safe_text(row.get("ownerName") or row.get("playerName"), "")
        if not player_name:
            continue
        market_key = _market_key_from_text(row.get("stat") or row.get("statLabel"), allow_fallback=True)
        if not market_key:
            continue
        mean_value = _numeric_hint(row.get("mean"))
        if mean_value is None:
            continue
        game_pk = _safe_int(row.get("gamePk") or row.get("game_pk"))
        lookup[(_normalized_market_text(player_name), market_key, game_pk)] = mean_value
    return lookup


def _mlb_team_by_player_market(selected_date: str) -> dict[tuple[str, str, int | None], str]:
    """Same shape/source as _mlb_pregame_mean_by_player_market, for "team"
    instead of "mean" -- backs _mlb_backfill_missing_projected_from_top_
    props' team backfill for the same mystery-origin candidate class
    (confirmed live: "Rhys Hoskins"/pick "UNDER Rhys Hoskins", real team
    "CLE" sitting right there in its daily_top_props row, structured "team"
    field on the candidate still blank)."""
    lookup: dict[tuple[str, str, int | None], str] = {}
    for row in _mlb_top_props_rows_from_artifact(selected_date):
        player_name = _safe_text(row.get("ownerName") or row.get("playerName"), "")
        if not player_name:
            continue
        market_key = _market_key_from_text(row.get("stat") or row.get("statLabel"), allow_fallback=True)
        if not market_key:
            continue
        team_value = _safe_text(row.get("team"), "")
        if not team_value:
            continue
        game_pk = _safe_int(row.get("gamePk") or row.get("game_pk"))
        lookup[(_normalized_market_text(player_name), market_key, game_pk)] = team_value
    return lookup


# _steam_candidates_for_sport's own market_key vs daily_top_props' raw
# "stat" field naming -- see the usage site in
# _mlb_backfill_missing_projected_from_top_props for the full story.
# Bidirectional so either spelling reaching this backfill (candidate side
# OR, in principle, a future artifact-side rename) still resolves.
_MLB_BACKFILL_MARKET_KEY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "rbis": ("rbi",),
    "rbi": ("rbis",),
    "runs_scored": ("runs",),
    "runs": ("runs_scored",),
}


def _mlb_backfill_missing_projected_from_top_props(sport: dict[str, Any], candidates: list[dict[str, Any]]) -> int:
    """Blank-only "projected"/"team" backfill for any MLB prop candidate,
    applied in place to the sport's slice of the pool -- regardless of
    which builder produced the candidate.

    2026-08-02 board audit follow-up: found a class of MLB prop candidate
    (confirmed live: "Miguel Rojas"/pick "OVER Miguel Rojas", narrative
    "detail" with the real mean baked into prose -- "...baseline comes in
    around 1.8 batter hits runs rbis...") whose exact originating builder
    could not be pinned down despite tracing every known MLB candidate
    source (home_rails pregame/live rails, daily_top_props direct reads,
    live-lens, steam). Its underlying daily_top_props row DOES exist with a
    real mean (confirmed: Miguel Rojas hits_runs_rbis mean 1.807, matching
    the "1.8" already visible in its own narrative text) -- it just never
    reaches this candidate's structured "projected" field. Reuses the exact
    same pregame-mean lookup _mlb_live_lens_prop_candidates_from_artifact
    already relies on rather than risk changing whichever function builds
    these rows -- returns how many candidates were filled, purely for the
    caller's own stage logging.

    2026-08-01 board audit follow-up (same mystery-origin class): "team"
    was ALSO blank on these ("Rhys Hoskins"/pick "UNDER Rhys Hoskins", real
    team "CLE" sitting right there in its daily_top_props row), so this now
    backfills both fields independently per candidate in one pass rather
    than bailing out as soon as "projected" alone is already filled.
    """
    if _safe_text(sport.get("slug"), "").lower() != "mlb":
        return 0
    selected_date = _safe_text(sport.get("context_label"), "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", selected_date):
        return 0
    pregame_means = _mlb_pregame_mean_by_player_market(selected_date)
    teams_by_market = _mlb_team_by_player_market(selected_date)
    if not pregame_means and not teams_by_market:
        return 0
    # Steam candidates confirmed live with game_pk=None (a real lifecycle
    # event whose game_id never resolved -- _steam_candidates_for_sport's
    # own game_id/game_pk fields end up "" / null for exactly these), so the
    # exact-match (subject, market_key, game_pk) lookup below always misses
    # for them even when a real per-player mean exists. A (subject,
    # market_key)-only fallback, ambiguous ONLY on a genuine doubleheader
    # with two DIFFERENT means for the same player+stat (rare) -- resolved
    # per pair, not blindly first-wins, so an ambiguous pair is correctly
    # left unresolved rather than risking the wrong game's number.
    means_by_subject_market: dict[tuple[str, str], float | None] = {}
    for (subject_key, market_key_val, _game_pk), mean_val in pregame_means.items():
        pair = (subject_key, market_key_val)
        if pair not in means_by_subject_market:
            means_by_subject_market[pair] = mean_val
        elif means_by_subject_market[pair] != mean_val:
            means_by_subject_market[pair] = None
    teams_by_subject_market: dict[tuple[str, str], str | None] = {}
    for (subject_key, market_key_val, _game_pk), team_val in teams_by_market.items():
        pair = (subject_key, market_key_val)
        if pair not in teams_by_subject_market:
            teams_by_subject_market[pair] = team_val
        elif teams_by_subject_market[pair] != team_val:
            teams_by_subject_market[pair] = None
    filled = 0
    for candidate in candidates:
        # 2026-08-01 board audit: this backfill only ever ran for
        # candidate_type == "prop" -- confirmed live, ~195 of MLB's ~360
        # Layer 2 candidates (over half the board) were standalone steam
        # candidates ("X · Steam" market label, _steam_candidates_for_sport)
        # that never merged with a matching analytical candidate (a real
        # steam/line move detected on a player+market the recommendation
        # engine simply never flagged, not a merge-key bug -- confirmed:
        # daily_top_props still has a real per-player row for these, just
        # never surfaced as a "recommended" pick). _steam_candidates_for_
        # sport hardcodes "projected": "-" unconditionally for exactly this
        # reason -- it has no sim access of its own. Steam candidates carry
        # player_name/market_key/game_pk in the same shape prop candidates
        # do, so the same pregame_means lookup resolves for them too.
        if _safe_text(candidate.get("candidate_type"), "").lower() not in ("prop", "steam"):
            continue
        needs_projected = _numeric_hint(candidate.get("projected")) is None
        needs_team = _safe_text(candidate.get("team"), "").strip() in ("", "-", "—")
        if not needs_projected and not needs_team:
            continue
        # Prefer player_name directly, same corruption guard
        # _prop_merge_dedup_key uses: a real player name is never itself
        # "... over ..."/"... under ..." text. _candidate_subject_key alone
        # isn't enough here -- it only parses a subject out of "name" when
        # that field embeds the selection ("Miguel Rojas Over 0.5 Hits");
        # this exact candidate class has a clean "name" with no selection
        # embedded at all, which _candidate_subject_key has no pattern for.
        player_name_text = _normalized_market_text(_safe_text(candidate.get("player_name"), ""))
        if player_name_text and any(f" {marker} " in f" {player_name_text} " for marker in ("over", "under")):
            player_name_text = ""
        subject = player_name_text or _normalized_market_text(_safe_text(_candidate_subject_key(candidate), ""))
        if not subject:
            continue
        # _candidate_market_key alone picks ONE focus (sorted first) out of
        # potentially several -- confirmed live: a real "Hitter Total Bases"
        # candidate's market_focuses held both "total" and "total_bases",
        # and alphabetical sort picked the too-generic "total" (never a key
        # in this artifact-sourced lookup, which always uses the specific
        # stat name), silently failing this whole backfill for the market
        # that most needs it. Try every focus, primary key first, so a
        # generic collision no longer blocks the specific match sitting
        # right behind it.
        market_key_candidates = [key for key in ([_candidate_market_key(candidate)] + sorted(_candidate_market_focuses(candidate))) if key]
        # Confirmed live: _steam_candidates_for_sport's own market_key
        # ("rbis", "runs_scored") doesn't match daily_top_props' raw "stat"
        # field naming ("rbi", "runs") -- a different naming convention, not
        # a coverage gap -- confirmed via cross-check: real rows exist for
        # both, just under the other spelling. This was ~77% (60/78) of all
        # remaining blank steam candidates in production after every other
        # fix in this same pass. _MLB_BACKFILL_MARKET_KEY_SYNONYMS is scoped
        # to this backfill only (not the shared _market_key_from_text/
        # _MARKET_FOCUS_ALIASES machinery) to keep blast radius contained.
        for key in list(market_key_candidates):
            market_key_candidates.extend(_MLB_BACKFILL_MARKET_KEY_SYNONYMS.get(key, ()))
        seen_keys: set[str] = set()
        ordered_market_keys = []
        for key in market_key_candidates:
            if key not in seen_keys:
                seen_keys.add(key)
                ordered_market_keys.append(key)
        if not ordered_market_keys:
            continue
        game_pk = _safe_int(candidate.get("game_pk") or candidate.get("gamePk"))
        resolved_any = False
        if needs_projected:
            mean_value = None
            for market_key in ordered_market_keys:
                mean_value = pregame_means.get((subject, market_key, game_pk))
                if mean_value is None:
                    mean_value = means_by_subject_market.get((subject, market_key))
                if mean_value is not None:
                    break
            if mean_value is not None:
                candidate["projected"] = f"{mean_value:.1f}"
                resolved_any = True
        if needs_team:
            # 2026-08-01 board audit follow-up: same mystery-origin
            # candidate class as the projected fix above (confirmed live:
            # "Rhys Hoskins"/pick "UNDER Rhys Hoskins", real team "CLE"
            # sitting right there in its daily_top_props row, structured
            # "team" field on the candidate still blank).
            team_value = None
            for market_key in ordered_market_keys:
                team_value = teams_by_market.get((subject, market_key, game_pk))
                if team_value is None:
                    team_value = teams_by_subject_market.get((subject, market_key))
                if team_value is not None:
                    break
            if team_value is not None:
                candidate["team"] = team_value
                resolved_any = True
        if resolved_any:
            filled += 1
    return filled


def _mlb_live_lens_prop_candidates_from_artifact(sport: dict[str, Any]) -> list[dict[str, Any]]:
    """Board candidates generated directly from MLB's live-lens artifact for
    LIVE games, not merely an enhancement layer on pre-existing daily_top_props
    candidates the way _mlb_hydrate_live_prop_projection is.

    daily_top_props_<date>.json (the sole source for every other MLB prop
    candidate function above) is written once, or a few times, per day --
    confirmed live: unchanged since 21:57 PM across a whole evening slate.
    live-lens now rotates continuously as live-odds-worker's tick refreshes
    real per-game props (confirmed live: counts.props 0 -> 134 the same
    night, after several independent artifact/timing bugs were fixed). Without
    this function, a prop that only ever shows up in live-lens -- one that
    never made the original static snapshot, or whose relevant player/market
    combination simply isn't in it -- could never become a board candidate no
    matter how strong its live edge, which is exactly the "same props for an
    hour" symptom #124/#128 both chased. Pregame stays untouched here
    (daily_top_props + the season betting card's own sim-vs-line edge already
    cover it correctly) -- this is deliberately live-games-only.
    """
    if _safe_text(sport.get("slug"), "").lower() != "mlb":
        return []
    selected_date = _safe_text(sport.get("context_label"), "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", selected_date):
        return []
    report = _mlb_live_lens_report_cached(selected_date, {})
    games = report.get("games") if isinstance(report, dict) else None
    if not isinstance(games, list):
        return []

    pregame_means = _mlb_pregame_mean_by_player_market(selected_date)
    candidates: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str, int]] = set()
    for game in games:
        if not isinstance(game, dict):
            continue
        status = game.get("status") if isinstance(game.get("status"), dict) else {}
        status_text = f"{_safe_text(status.get('abstract'), '')} {_safe_text(status.get('detailed'), '')}".strip().lower()
        if not any(token in status_text for token in ("live", "in progress", "warmup")):
            continue
        # 2026-07-31 board-audit follow-up: these candidates never carried
        # status_display/game_state at all, only is_live=True below. Fine
        # for a brand-new standalone candidate (_recommendation_lane's own
        # fallback already treats is_live=True + no status text as "live"),
        # but it left nothing correct for the prop-merge dedup pass
        # (_merge_duplicate_prop_candidates) to override a stale
        # duplicate's status_display WITH -- so a merged row could end up
        # is_live=True yet status_display still "Warmup"/"scheduled" from
        # the stale side, and _recommendation_lane checks status text
        # first, landing back on lane="pregame" despite is_live=True.
        # Confirmed live. Stamp the real resolved status here since it's
        # already known for this exact game.
        resolved_status_display = _safe_text(status.get("detailed"), _safe_text(status.get("abstract"), ""))
        game_pk = _safe_int(game.get("gamePk"))
        rows = game.get("trackedProps") if isinstance(game.get("trackedProps"), list) else None
        if not rows:
            rows = game.get("props") if isinstance(game.get("props"), list) else []
        matchup_obj = game.get("matchup") if isinstance(game.get("matchup"), dict) else {}
        away = matchup_obj.get("away") if isinstance(matchup_obj.get("away"), dict) else {}
        home = matchup_obj.get("home") if isinstance(matchup_obj.get("home"), dict) else {}
        away_abbr = _safe_text(away.get("abbr"), "")
        home_abbr = _safe_text(home.get("abbr"), "")
        matchup_text = f"{away_abbr} @ {home_abbr}" if away_abbr or home_abbr else "-"

        for row in rows:
            if not isinstance(row, dict):
                continue
            player_name = _safe_text(row.get("playerName"), "")
            if not player_name:
                continue
            market_label = _safe_text(row.get("marketLabel"), "") or _market_label(_market_key_from_text(row.get("market"), allow_fallback=True))
            market_key = _market_key_from_text(market_label or row.get("market"), allow_fallback=True)
            if not market_key:
                continue
            line_value = _numeric_hint(row.get("line"))
            selection_label = _safe_text(row.get("selection"), "Over") or "Over"
            selection_direction = 1 if selection_label.lower() == "over" else -1 if selection_label.lower() == "under" else 0
            odds_value = _american_odds_value(row.get("odds"))
            odds_text = (f"+{int(odds_value)}" if odds_value > 0 else str(int(odds_value))) if odds_value is not None else "-"
            # estimatedWinProb is already the probability of THIS row's own
            # selection (over or under, whichever the live pipeline picked) --
            # not the raw over-probability -- matching how the rest of this
            # file already treats the two as interchangeable fallbacks of
            # each other (see _normalize_live_prop_row, mlb/live_lens.py).
            model_prob = _numeric_hint(row.get("estimatedWinProb"))
            if model_prob is None:
                model_prob = _numeric_hint(row.get("modelProbOver"))
            live_projection_value = _numeric_hint(row.get("liveProjection"))
            actual_value = _numeric_hint(row.get("actual"))
            ranking_score = _numeric_hint(row.get("rankingScore"))
            pick = f"{selection_label} {line_value:.1f}" if line_value is not None else selection_label
            dedupe_key = (_normalized_market_text(player_name), market_key, pick, game_pk or 0)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            score = (float(model_prob or 0.0) * 60.0) + max(0.0, float(ranking_score or 0.0)) * 40.0
            pregame_mean = pregame_means.get((_normalized_market_text(player_name), market_key, game_pk))
            projected_text = f"{pregame_mean:.1f}" if pregame_mean is not None else "-"
            live_projection_text = f"{live_projection_value:.1f}" if live_projection_value is not None else "-"
            confidence_text = f"{model_prob * 100.0:.1f}%" if model_prob is not None else "-"
            candidates.append(
                {
                    "candidate_type": "prop",
                    "sport": _safe_text(sport.get("name"), "MLB"),
                    "sport_slug": "mlb",
                    "surface_key": "live",
                    "surface_title": "Live lens props",
                    "name": (
                        f"{player_name} {selection_label} {line_value:.1f} {market_label}"
                        if line_value is not None
                        else f"{player_name} {selection_label} {market_label}"
                    ),
                    "market": market_label,
                    "market_key": market_key,
                    "pick": pick,
                    "player_name": player_name,
                    "matchup": matchup_text,
                    "team": away_abbr or home_abbr or "-",
                    "context_label": selected_date,
                    "game_pk": game_pk,
                    "game_id": _safe_text(game_pk, ""),
                    "event_id": _safe_text(game_pk, ""),
                    "line": f"{line_value:.1f}" if line_value is not None else "-",
                    "odds": odds_text,
                    "projected": projected_text,
                    "model_probability": model_prob,
                    "confidence": confidence_text,
                    "live_projection": live_projection_text,
                    "actual": f"{actual_value:.1f}" if actual_value is not None else "-",
                    "is_live": True,
                    "is_final": False,
                    "status_display": resolved_status_display,
                    "game_state": resolved_status_display,
                    "selection_direction": selection_direction,
                    "score": score,
                    "href": f"/mlb/live-lens?date={selected_date}",
                    "href_label": "Open live lens",
                    "writeup": (
                        f"Live lens {market_label.lower()} view for {player_name}."
                        + (f" Model win probability {model_prob * 100.0:.1f}%." if model_prob is not None else "")
                    ),
                    "display_pills": [
                        pill
                        for pill in (
                            f"Line {line_value:.1f}" if line_value is not None else "",
                            f"Odds {odds_text}" if odds_text != "-" else "",
                            f"Sim% {confidence_text}" if confidence_text != "-" else "",
                            f"Live Proj {live_projection_text}" if live_projection_text != "-" else "",
                        )
                        if pill
                    ],
                }
            )
    return candidates


def _soccer_live_lens_prop_candidates_from_artifact(sport: dict[str, Any]) -> list[dict[str, Any]]:
    """Soccer's mirror of _mlb_live_lens_prop_candidates_from_artifact above.

    Confirmed live 2026-08-01: _SoccerDataProvider.live_props()
    (syndicate/blueprints/home.py) is hardcoded `return []` -- soccer has
    never produced a single live prop candidate on the Layer 2 board no
    matter how many real matches were in progress, even though the live-lens
    loop (scripts/poll_soccer_live_state.py, wired into live_lens_loop.py
    2026-07-31) has been writing real per-match live_player_props all along.
    The market itself differs from soccer's pregame prop (anytime-goalscorer
    probability): live tracking only ever projects total SHOTS per player
    (project_live_player_props, syndicate/features/soccer/features/
    live_lens.py) -- there is no live-updated anytime-goalscorer number to
    align against a pregame one, so this surfaces "Shots" as its own market
    rather than forcing a false match onto the pregame prop's market.

    Soccer is week-keyed and tracks several leagues at once (see
    _SoccerDataProvider), unlike MLB's single date+sport -- sport's own
    context_label here is a week string ("MLS 2026 Week 18"), not a date, so
    this resolves today's real calendar date directly and scans every
    active league for it rather than trying to parse one out of the label.
    """
    if _safe_text(sport.get("slug"), "").lower() != "soccer":
        return []
    try:
        from syndicate.features.soccer.sources import active_leagues_for_date
        from syndicate.features.soccer.sources import league_display_name
        from syndicate.features.soccer.sources import live_state_payload
    except Exception:
        return []

    today = central_today_iso()
    try:
        leagues = active_leagues_for_date(today)
    except Exception:
        leagues = []
    if not leagues:
        return []

    candidates: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for league in leagues:
        try:
            payload = live_state_payload(league, today)
        except Exception:
            continue
        games = payload.get("games") if isinstance(payload, dict) else None
        if not isinstance(games, dict):
            continue
        league_label = league_display_name(league)
        for event_id, game in games.items():
            if not isinstance(game, dict):
                continue
            live_props = game.get("live_player_props") if isinstance(game.get("live_player_props"), list) else []
            if not live_props:
                continue
            home_team = _safe_text(game.get("home_team"), "")
            away_team = _safe_text(game.get("away_team"), "")
            matchup_text = f"{away_team} @ {home_team}" if away_team or home_team else "-"
            for row in live_props:
                if not isinstance(row, dict):
                    continue
                player_name = _safe_text(row.get("player_name"), "")
                if not player_name:
                    continue
                side = _safe_text(row.get("side"), "").strip().lower()
                team = away_team if side == "away" else home_team if side == "home" else "-"
                shots_so_far = _numeric_hint(row.get("shots_so_far"))
                projected_final = _numeric_hint(row.get("projected_final_shots"))
                over_probs = row.get("shots_over_probabilities") if isinstance(row.get("shots_over_probabilities"), dict) else {}
                # Pick the shot line closest to the model's own projected
                # final mean -- a stable, model-anchored choice rather than
                # always defaulting to the shortest (near-certain) line.
                best_line: float | None = None
                best_prob: float | None = None
                reference = projected_final if projected_final is not None else 0.0
                for line_text, prob in over_probs.items():
                    line_value = _numeric_hint(line_text)
                    prob_value = _numeric_hint(prob)
                    if line_value is None or prob_value is None:
                        continue
                    if best_line is None or abs(line_value - reference) < abs(best_line - reference):
                        best_line = line_value
                        best_prob = prob_value
                if best_line is None:
                    continue
                dedupe_key = (_normalized_market_text(player_name), _safe_text(event_id, ""), f"{best_line:.1f}")
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                confidence_text = f"{best_prob * 100.0:.1f}%" if best_prob is not None else "-"
                projected_text = f"{projected_final:.1f}" if projected_final is not None else "-"
                candidates.append(
                    {
                        "candidate_type": "prop",
                        "sport": league_label,
                        "sport_slug": "soccer",
                        "surface_key": "live",
                        "surface_title": "Live lens props",
                        "name": f"{player_name} Over {best_line:.1f} Shots",
                        "market": "Shots",
                        "market_key": "shots",
                        "pick": f"Over {best_line:.1f}",
                        "player_name": player_name,
                        "matchup": matchup_text,
                        "team": team,
                        "context_label": today,
                        "game_id": _safe_text(event_id, ""),
                        "event_id": _safe_text(event_id, ""),
                        "line": f"{best_line:.1f}",
                        "odds": "-",
                        "projected": projected_text,
                        "model_probability": best_prob,
                        "confidence": confidence_text,
                        "live_projection": projected_text,
                        "actual": f"{shots_so_far:.0f}" if shots_so_far is not None else "-",
                        "is_live": True,
                        "is_final": False,
                        "status_display": "Live",
                        "game_state": "Live",
                        "selection_direction": 1,
                        "score": max(0.0, float(best_prob or 0.0)) * 60.0,
                        "href": f"/soccer/{league}/live-lens",
                        "href_label": "Open live lens",
                        "writeup": (
                            f"Live lens shots view for {player_name}."
                            + (f" Model over probability {best_prob * 100.0:.1f}%." if best_prob is not None else "")
                        ),
                        "display_pills": [
                            pill
                            for pill in (
                                f"Line {best_line:.1f}",
                                f"Sim% {confidence_text}" if confidence_text != "-" else "",
                                f"So far {shots_so_far:.0f}" if shots_so_far is not None else "",
                            )
                            if pill
                        ],
                    }
                )
    return candidates


_GAME_LEVEL_MARKET_KEYWORDS = ("moneyline", "spread", "total", "puck line", "puck_line", "run line", "run_line", "game bet")


def _is_game_level_market(market_text: Any) -> bool:
    lowered = _safe_text(market_text, "").strip().lower()
    if not lowered:
        return True
    if lowered == "ats":
        return True
    # "Hitter Total bases" / "Pitcher Total outs" (MLB's per-player prop
    # rows -- market = f"{market_prefix} {market_label}") legitimately
    # contain "total" as a real word, indistinguishable from the
    # team-level "Total" market by keyword alone. Confirmed live
    # 2026-07-22: every "game"-type candidate on the board was actually
    # "hitter total bases", a mislabeled player prop, while genuine
    # Moneyline/Spread/Total game candidates never appeared at all. Any
    # Hitter/Pitcher-prefixed market is always a player prop.
    if lowered.startswith("hitter ") or lowered.startswith("pitcher "):
        return False
    return any(keyword in lowered for keyword in _GAME_LEVEL_MARKET_KEYWORDS)


def _game_candidates_for_sport(sport: dict[str, Any]) -> list[dict[str, Any]]:
    dashboard_games = sport.get("dashboard_games") if isinstance(sport.get("dashboard_games"), list) else []
    # #68. The worker generated ONE candidate for all of MLB on 2026-07-26
    # while the identical function run over production's own /mlb/api/cards
    # payload produced 38 -- 22 from a single live game, all priced and edged
    # ("OVER Bryce Eldridge, Hitter Hits, odds 280, edge 39.2%"). Same code,
    # so the worker's dashboard_games must be arriving without the market
    # blocks _game_bet_candidates_from_game reads. Which one is missing cannot
    # be established from outside the worker: web and the worker read separate
    # Render disks, and every artifact_status trace on that path reports the
    # sim/live-lens artifacts rather than the per-game market payload.
    #
    # Bounded deliberately -- two games per sport, presence and size only, no
    # payload contents -- because the last round of per-game diagnostics on
    # this path buried the INTEL_TRACE rows it was meant to support.
    for game in dashboard_games[:2]:
        if not isinstance(game, dict):
            continue
        _intel_trace(
            "game_candidate_inputs",
            sport=_safe_text(sport.get("slug"), "sport").lower(),
            game_state=_safe_text(game.get("game_state"), ""),
            is_live=bool(game.get("is_live")),
            blocks={
                key: (len(value) if isinstance(value, (list, dict)) else 0)
                for key, value in (
                    ("game_market_recommendations", game.get("game_market_recommendations")),
                    ("gameMarkets", game.get("gameMarkets")),
                    ("betting", game.get("betting")),
                    ("gameLens", game.get("gameLens")),
                    ("markets", game.get("markets")),
                    ("shared_top_play_rows", game.get("shared_top_play_rows")),
                    ("shared_prop_rows", game.get("shared_prop_rows")),
                )
            },
        )
    candidates: list[dict[str, Any]] = []
    for game in dashboard_games:
        if not isinstance(game, dict):
            continue
        for row in _game_bet_candidates_from_game(sport, game, fallback_epoch=0.0):
            if not isinstance(row, dict):
                continue
            row = dict(row)
            # _game_bet_candidates_from_game's game_market_recommendations loop
            # also surfaces per-game PLAYER props (market == "props") mixed in
            # with true team/game-level markets (moneyline/spread/total/ats) --
            # this used to force candidate_type="game" on every row unconditionally,
            # mislabeling player props (e.g. "Gabby Williams OVER 1.5") as game
            # markets. Confirmed live 2026-07-21 on the WNBA board.
            row["candidate_type"] = "game" if _is_game_level_market(row.get("market")) else "prop"
            candidates.append(row)
    return candidates


def _candidate_is_final(candidate: dict[str, Any]) -> bool:
    if bool(candidate.get("is_final")):
        return True
    terminal_text = " ".join(
        _safe_text(candidate.get(field), "")
        for field in ("status_badge", "status_line", "status_display", "status_context", "detail", "summary", "score_kind")
    ).lower()
    return any(token in terminal_text for token in ("final", "game over", "completed"))


_CANDIDATE_INACTIVE_PLAYER_TOKENS = (
    "inactive",
    "not active",
    "did not play",
    "did not dress",
    "dnp",
    "out",
    "suspended",
)


def _candidate_state_text(candidate: dict[str, Any]) -> str:
    return " ".join(
        _safe_text(candidate.get(field), "")
        for field in ("status_badge", "status_line", "status_display", "status_context", "game_state", "detail", "summary")
    ).lower()


# No real game stays "live" this long -- a candidate still claiming is_live
# with data this old is stale tracking state (the upstream game/live_state
# object frozen at whatever it last was before tracking stopped for that
# game), not a genuinely ongoing game. Confirmed live 2026-07-21: settled
# WNBA games from a prior date showing up on the board perpetually marked
# "live" because nothing ever re-checked their actual final status once
# tracking moved on. Generous ceiling (real games rarely exceed ~4 hours)
# to avoid excluding a genuinely slow/delayed live game.
_MAX_PLAUSIBLE_LIVE_AGE_SECONDS = 8 * 60 * 60


def _candidate_live_claim_is_stale(candidate: dict[str, Any]) -> bool:
    claims_live = bool(candidate.get("is_live")) or _safe_text(candidate.get("game_state"), "").lower() == "live"
    if not claims_live:
        return False
    try:
        updated_epoch_value = float(candidate.get("updated_epoch"))
    except (TypeError, ValueError):
        # Reverted 2026-07-22: a prior change here treated a missing
        # timestamp as automatically stale, on the theory that a live claim
        # with no evidence behind it was suspect. In practice, updated_epoch
        # is only ever populated by _game_row_updated_epoch (home.py), which
        # falls back to a hardcoded 0.0 whenever a game lacks its own
        # updated_at-style field -- the COMMON case, not a rare one. That
        # change silently disqualified nearly every genuinely-live candidate
        # from ever showing as live. Trust the claim when there's simply no
        # timestamp evidence either way; only reject a claim backed by a
        # timestamp that's actually, demonstrably old (below).
        return False
    if updated_epoch_value <= 0:
        return False
    return (time.time() - updated_epoch_value) > _MAX_PLAUSIBLE_LIVE_AGE_SECONDS


_CANDIDATE_LIVE_STATE_MARKERS = (
    "live",
    "in progress",
    "in-progress",
    "halftime",
    "intermission",
)


def _bind_candidate_state(candidate: dict[str, Any]) -> None:
    status_display = _safe_text(candidate.get("status_display"), "")
    status_context = _safe_text(candidate.get("status_context"), "")
    game_state = _safe_text(candidate.get("game_state"), "")
    if not game_state and (status_display or status_context):
        # status_display/status_context on a candidate that fell back to
        # pregame data is often just a scheduled start time (e.g. "6:10 PM
        # CT"), not an actual game state -- promoting it verbatim used to
        # mislabel a scheduled game as if it might be live, since nothing
        # here ever checked whether the text said anything about live/final
        # state at all. Confirmed live 2026-07-22: candidates for genuinely
        # in-progress MLB games showed a raw scheduled-time string as their
        # game_state. Only backfill when there's a real signal -- the
        # candidate already claims live, or the text itself names a
        # live/final state -- otherwise leave game_state unset rather than
        # echoing a meaningless scheduled-time string.
        candidate_text = f"{status_display} {status_context}".lower()
        has_live_marker = bool(candidate.get("is_live")) or any(
            marker in candidate_text for marker in _CANDIDATE_LIVE_STATE_MARKERS
        )
        if has_live_marker or _candidate_is_final(candidate):
            candidate["game_state"] = status_display or status_context
    if not status_display and game_state:
        candidate["status_display"] = game_state
    if not status_context and candidate.get("status_display"):
        candidate["status_context"] = _safe_text(candidate.get("status_display"), "")


def _candidate_is_player_level_market(candidate: dict[str, Any]) -> bool:
    """True for any candidate that represents a specific player's stat line
    -- a real prop candidate, OR a steam candidate built on a player-level
    market (_steam_candidates_for_sport only ever sets player_name for a
    genuine player prop, never a team/game-level market -- see its own
    comment on that field). 2026-08-01 board audit follow-up: the settled-
    prop and inactive-player guards below were gated to candidate_type ==
    "prop" only, so a steam candidate on the exact same removed player or
    already-decided line stayed on the board indefinitely -- confirmed
    live, steam is roughly HALF of MLB's daily candidate pool, so this was
    a large share of exactly the staleness the user asked to fix. Excludes
    game-level steam moves (moneyline/spread/total), which have no
    per-player monotonic-stat semantics to apply this logic to.
    """
    candidate_type = _safe_text(candidate.get("candidate_type"), "").lower()
    if candidate_type == "prop":
        # A "prop" candidate is player-level by definition/construction --
        # unconditional, matching this guard's original behavior before the
        # steam extension (some real prop candidates, and several existing
        # tests' minimal fixtures, don't happen to set player_name even
        # though every real builder does in practice; don't require it).
        return True
    if candidate_type == "steam":
        # Steam is the one type that genuinely mixes player-level and
        # team/game-level candidates -- player_name is the only reliable
        # discriminator here (_steam_candidates_for_sport only ever sets it
        # for a genuine player prop).
        return bool(_safe_text(candidate.get("player_name"), ""))
    return False


def _candidate_prop_outcome_decided(candidate: dict[str, Any]) -> str | None:
    """"hit" or "missed" once a live prop's outcome is already
    mathematically locked in, else None (still undecided, or not enough
    data to tell).

    Every player-prop market on this board is a monotonic, non-decreasing
    counting stat within a single game (hits, points, assists, strikeouts,
    shots, ...) -- once the live actual crosses the line, the outcome can
    never revert for the rest of that game, regardless of which side
    (over/under) was originally recommended. Board audit 2026-08-01: user
    asked for a settled prop to be removed or clearly designated rather
    than left showing as if it were still a live opportunity -- there was
    previously no code anywhere comparing actual against line at all.
    """
    if not _candidate_is_player_level_market(candidate):
        return None
    line_value = _numeric_hint(candidate.get("line"))
    actual_value = _numeric_hint(candidate.get("actual"))
    if line_value is None or actual_value is None or actual_value <= line_value:
        return None
    pick_text = _safe_text(candidate.get("pick"), "").strip().lower()
    if pick_text.startswith("over"):
        return "hit"
    if pick_text.startswith("under"):
        return "missed"
    return None


def _apply_candidate_state_guard(candidate: dict[str, Any]) -> None:
    _bind_candidate_state(candidate)
    if _candidate_is_final(candidate):
        candidate["state_invalid"] = True
        candidate.setdefault("state_note", "Final or settled game state excluded.")
        return
    if _candidate_live_claim_is_stale(candidate):
        candidate["state_invalid"] = True
        candidate.setdefault("state_note", "Stale live-state data excluded (no update in over 8 hours).")
        return
    if not _candidate_is_player_level_market(candidate):
        return
    prop_outcome = _candidate_prop_outcome_decided(candidate)
    if prop_outcome is not None:
        candidate["state_invalid"] = True
        candidate.setdefault("state_note", f"Prop already {prop_outcome} -- outcome decided, no longer a live opportunity.")
        candidate["prop_outcome"] = prop_outcome
        return
    status_text = _candidate_state_text(candidate)
    if any(re.search(rf"(?<![a-z]){re.escape(token)}(?![a-z])", status_text) for token in _CANDIDATE_INACTIVE_PLAYER_TOKENS):
        candidate["state_invalid"] = True
        candidate.setdefault("state_note", "Inactive player state excluded.")


def _mlb_actual_payload_for_candidate(
    context_label: str,
    game_pk: int,
    cache: dict[int, dict[str, Any] | None],
) -> dict[str, Any] | None:
    try:
        from syndicate.blueprints.home import _mlb_actual_payload_for_game
    except Exception:
        return None
    return _mlb_actual_payload_for_game(context_label, game_pk, cache)


def _mlb_current_pitcher(actual_payload: dict[str, Any] | None) -> tuple[int | None, str | None]:
    if not isinstance(actual_payload, dict):
        return None, None
    current_play = ((actual_payload.get("liveData") or {}).get("plays") or {}).get("currentPlay")
    matchup = (current_play or {}).get("matchup") if isinstance(current_play, dict) else {}
    pitcher = (matchup or {}).get("pitcher") if isinstance(matchup, dict) else {}
    pitcher_id = _safe_int((pitcher or {}).get("id")) if isinstance(pitcher, dict) else None
    pitcher_name = _safe_text((pitcher or {}).get("fullName"), "") if isinstance(pitcher, dict) else ""
    return pitcher_id, pitcher_name or None


def _mlb_probable_pitcher_side(actual_payload: dict[str, Any] | None, pitcher_id: int | None, pitcher_name: str | None) -> str | None:
    probable_pitchers = ((actual_payload or {}).get("gameData") or {}).get("probablePitchers")
    if not isinstance(probable_pitchers, dict):
        return None
    normalized_target = re.sub(r"\s+", " ", str(pitcher_name or "").strip().lower())
    for side in ("away", "home"):
        probable = probable_pitchers.get(side)
        if not isinstance(probable, dict):
            continue
        probable_id = _safe_int(probable.get("id"))
        probable_name = re.sub(r"\s+", " ", _safe_text(probable.get("fullName"), "").lower())
        if pitcher_id is not None and probable_id is not None and int(probable_id) == int(pitcher_id):
            return side
        if normalized_target and probable_name and probable_name == normalized_target:
            return side
    return None


def _mlb_candidate_live_state(candidate: dict[str, Any], actual_payload: dict[str, Any] | None) -> dict[str, Any]:
    state: dict[str, Any] = {}
    if not isinstance(actual_payload, dict):
        return state
    status = ((actual_payload.get("gameData") or {}).get("status")) if isinstance((actual_payload.get("gameData") or {}), dict) else {}
    abstract_state = _safe_text((status or {}).get("abstractGameState"), "")
    detailed_state = _safe_text((status or {}).get("detailedState"), "")
    status_code = _safe_text((status or {}).get("statusCode"), "")
    snapshot_timestamp = _safe_text(
        candidate.get("updated_at"),
        _safe_text(candidate.get("timestamp"), _safe_text(candidate.get("last_updated"), _safe_text(candidate.get("state_last_updated"), ""))),
    )
    if abstract_state or detailed_state:
        state["status_display"] = detailed_state or abstract_state
    # #100: delegates to the shared canonical predicate (syndicate.features.
    # mlb.game_state) instead of keeping its own inline copy -- this was the
    # confirmed-correct implementation the consolidation canonicalized on.
    if _mlb_status_is_final(abstract_state, detailed_state):
        state["is_final"] = True
        state["is_live"] = False
    elif detailed_state:
        state["is_live"] = _mlb_status_is_live(abstract_state, detailed_state)

    current_pitcher_id, current_pitcher_name = _mlb_current_pitcher(actual_payload)
    if current_pitcher_id is not None:
        state["current_pitcher_id"] = current_pitcher_id
    if current_pitcher_name:
        state["current_pitcher_name"] = current_pitcher_name

    market_text = _safe_text(candidate.get("market"), "").lower()
    pitcher_id = _safe_int(candidate.get("pitcher_id"))
    pitcher_name = _safe_text(candidate.get("player_name"), _safe_text(candidate.get("name"), ""))
    if market_text.startswith("pitcher") and (pitcher_id is not None or pitcher_name):
        side = _mlb_probable_pitcher_side(actual_payload, pitcher_id, pitcher_name)
        if side:
            try:
                from syndicate.features.mlb.cards import _starter_removed_from_actual_payload

                removed = _starter_removed_from_actual_payload(
                    actual_payload,
                    side=side,
                    starter_id=pitcher_id,
                    starter_name=pitcher_name,
                )
            except Exception:
                removed = False
            if removed:
                current_label = current_pitcher_name or "another pitcher"
                state["state_invalid"] = True
                state["state_note"] = f"{pitcher_name or 'The listed pitcher'} is no longer the current pitcher; {current_label} is on the mound now."
    elif not market_text.startswith("pitcher"):
        # 2026-08-01 board audit follow-up: the pitcher-removed check above
        # has no hitter equivalent -- a hitter pinch hit for or
        # double-switched out of the lineup mid-game stayed on the board as
        # a live opportunity indefinitely (until the whole game went
        # Final). Applies to any hitter-market candidate, not just
        # candidate_type=="prop" -- a steam candidate on the same removed
        # player is exactly as stale.
        batter_id = _safe_int(candidate.get("batter_id") or candidate.get("player_id"))
        batter_name = _safe_text(candidate.get("player_name"), "")
        if batter_id is not None or batter_name:
            try:
                from syndicate.features.mlb.cards import _hitter_removed_from_actual_payload

                removed = _hitter_removed_from_actual_payload(actual_payload, batter_id=batter_id, batter_name=batter_name)
            except Exception:
                removed = False
            if removed:
                state["state_invalid"] = True
                state["state_note"] = f"{batter_name or 'This player'} is no longer in the active lineup for this game."
    if _safe_int(candidate.get("gamePk")) == 823931:
        logger.info(
            "MLB live-state diagnostic gamePk=%s snapshot_timestamp=%s abstractGameState=%s detailedState=%s statusCode=%s decision=%s",
            _safe_int(candidate.get("gamePk")) or candidate.get("gamePk"),
            snapshot_timestamp or "-",
            abstract_state or "-",
            detailed_state or "-",
            status_code or "-",
            "drop" if bool(state.get("is_final")) or bool(state.get("state_invalid")) else "keep",
        )
    return state


def _mlb_live_lens_report_cached(context_label: str, cache: dict[str, dict[str, Any] | None]) -> dict[str, Any] | None:
    if context_label in cache:
        return cache[context_label]
    # _mlb_repo_artifact_path (used elsewhere in this file only for cosmetic
    # advanced_context path display) resolves via default_mlb_source_root(),
    # which returns SYNDICATE_MLB_SOURCE_ROOT verbatim with no "source_artifacts"
    # segment -- wrong once that env var is set (true in every deployed
    # environment). live_lens_report_path resolves the same way every other
    # working MLB artifact reader in this file does (daily_top_props_path,
    # etc.), via _resolve_data_path_with_reconcile's artifact-roots-first
    # search. Confirmed live: the wrong path silently returned None here,
    # which is exactly why the live-projection hydration below never fired.
    path = mlb_live_lens_report_path(context_label)
    payload = mlb_load_json_file(path)
    cache[context_label] = payload if isinstance(payload, dict) else None
    return cache[context_label]


def _mlb_live_lens_prop_rows_for_game(context_label: str, game_pk: int, cache: dict[str, dict[str, Any] | None]) -> list[dict[str, Any]]:
    report = _mlb_live_lens_report_cached(context_label, cache)
    games = report.get("games") if isinstance(report, dict) else None
    if not isinstance(games, list):
        return []
    for game in games:
        if not isinstance(game, dict) or _safe_int(game.get("gamePk")) != game_pk:
            continue
        # trackedProps is the single curated row per prop ("tier": "official");
        # props/liveProps duplicate the same data across more prop types but
        # aren't guaranteed present, so fall back to them if trackedProps is
        # empty (e.g. before the first live tick has run for this game).
        rows = game.get("trackedProps")
        if isinstance(rows, list) and rows:
            return [row for row in rows if isinstance(row, dict)]
        rows = game.get("props")
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    return []


def _mlb_hydrate_live_prop_projection(candidate: dict[str, Any], live_rows: list[dict[str, Any]]) -> None:
    # Root cause of a real production bug: MLB prop candidates (both the
    # top-props-artifact pipeline and the daily-update-narrative pipeline)
    # only ever carry a PREGAME projection -- neither reads the live_lens
    # report's already-computed live projection (actual K's so far, live
    # rest-of-game projection), even once is_live flips true. That report is
    # refreshed on its own live tick and already has the right numbers; this
    # just attaches them to whichever candidate matches by player+market+line.
    if not live_rows:
        return
    candidate_name = _normalized_market_text(
        _safe_text(candidate.get("entity"), _safe_text(candidate.get("player_name"), _safe_text(candidate.get("name"), "")))
    )
    if not candidate_name:
        return
    candidate_line = _numeric_hint(candidate.get("line"))
    candidate_market = _normalized_market_text(str(_safe_text(candidate.get("market"), "")).replace("Pitcher", "").replace("pitcher", ""))
    matched_row: dict[str, Any] | None = None
    for row in live_rows:
        row_name = _normalized_market_text(_safe_text(row.get("playerName"), ""))
        names_overlap = bool(row_name) and (row_name in candidate_name or candidate_name in row_name)
        if not names_overlap:
            continue
        row_market = _normalized_market_text(_safe_text(row.get("marketLabel"), ""))
        if candidate_market and row_market and candidate_market not in row_market and row_market not in candidate_market:
            continue
        row_line = _numeric_hint(row.get("line"))
        if candidate_line is not None and row_line is not None and abs(row_line - candidate_line) > 0.01:
            continue
        matched_row = row
        break
    if matched_row is None:
        return
    live_projection_value = _numeric_hint(matched_row.get("liveProjection"))
    if live_projection_value is not None:
        candidate["live_projection"] = f"{live_projection_value:.1f}"
    actual_value = _numeric_hint(matched_row.get("actual"))
    if actual_value is not None:
        candidate["actual"] = f"{actual_value:.1f}"


def _apply_live_state_context_to_candidates(
    candidates: list[dict[str, Any]],
    *,
    mlb_actual_cache: dict[int, dict[str, Any] | None] | None = None,
    mlb_live_lens_cache: dict[str, dict[str, Any] | None] | None = None,
) -> None:
    # Callers that score many candidates in a loop (e.g. _score_candidates)
    # must pass shared cache dicts through -- each unique game_pk's raw feed
    # file and each context_label's live-lens report are otherwise reloaded
    # and reparsed from disk on every single candidate instead of once per
    # game, which is what made scoring ~200 candidates take 30-350s (and
    # spike container memory) instead of the sub-second cost a handful of
    # per-game file reads should be.
    if mlb_actual_cache is None:
        mlb_actual_cache = {}
    if mlb_live_lens_cache is None:
        mlb_live_lens_cache = {}
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        sport_slug = _safe_text(candidate.get("sport_slug"), "").lower()
        if sport_slug != "mlb":
            continue
        # 2026-08-01 board audit: a candidate with no context_label got
        # silently skipped here entirely -- confirmed live, a genuinely
        # stale MLB game-level moneyline candidate (real game ended hours
        # earlier, but the row still claimed is_live=True with the
        # game's last-known live score frozen in "actual") never got its
        # live state re-checked against the real current game status
        # because this exact field was null, even though game_date/
        # source_board_date (which resolve this same game's real date
        # just as well for this lookup) were both present on the same
        # row. Falls back to either before giving up.
        context_label = _safe_text(
            candidate.get("context_label"),
            _safe_text(candidate.get("game_date"), _safe_text(candidate.get("source_board_date"), "")),
        )
        game_pk = _safe_int(candidate.get("game_pk"))
        if not context_label or game_pk is None:
            continue
        actual_payload = _mlb_actual_payload_for_candidate(context_label, int(game_pk), mlb_actual_cache)
        live_state = _mlb_candidate_live_state(candidate, actual_payload)
        for key, value in live_state.items():
            if value not in {None, ""}:
                candidate[key] = value
        # Root-caused 2026-07-31: _mlb_candidate_live_state never returns a
        # "game_state" key, but candidates carry a separate `game_state`
        # field stamped by whichever builder created them (e.g.
        # _prop_candidate_from_item, from a slower/differently-cadenced
        # dashboard artifact) -- so this pass could correct `is_live`/
        # `status_display` while leaving a stale/disagreeing `game_state`
        # untouched on the same row. Confirmed live against production: a
        # candidate whose `game_state` literally showed
        # {'abstract': 'Live', ...} while `is_live`/`status_display` still
        # said "Scheduled". Force both to the same freshly-resolved value.
        resolved_status_display = live_state.get("status_display")
        if resolved_status_display not in (None, ""):
            candidate["game_state"] = resolved_status_display
        # A player-prop Steam candidate (_steam_candidates_for_sport,
        # candidate_type="steam") has the exact same name/market/line shape
        # a "prop"-type candidate does -- it only ever gets player_name set
        # when market_key is NOT a game-side market (moneyline/spread/
        # total), see that function's own player_name assignment -- but this
        # gate was hardcoded to candidate_type == "prop" alone, so every
        # player-prop steam candidate's live_projection/actual stayed "-"
        # even when live, regardless of how fresh the live-lens report was.
        # Confirmed a real, already-documented gap (30a6cff9). Game-level
        # steam candidates (moneyline/spread/total moves, no player_name)
        # correctly stay excluded -- they'd never match a player-prop row
        # anyway, and already get an "actual" value from
        # _steam_candidates_for_sport's own combined-score fallback.
        candidate_type_text = _safe_text(candidate.get("candidate_type"), "")
        is_prop_shaped_candidate = candidate_type_text == "prop" or (
            candidate_type_text == "steam" and bool(candidate.get("player_name"))
        )
        if bool(candidate.get("is_live")) and is_prop_shaped_candidate:
            live_rows = _mlb_live_lens_prop_rows_for_game(context_label, int(game_pk), mlb_live_lens_cache)
            _mlb_hydrate_live_prop_projection(candidate, live_rows)


def _candidate_market_focuses(candidate: dict[str, Any]) -> set[str]:
    market_text = " ".join(
        [
            _safe_text(candidate.get("market"), ""),
            _safe_text(candidate.get("name"), ""),
            _safe_text(candidate.get("pick"), ""),
        ]
    )
    focuses: set[str] = set()
    explicit_market_key = _safe_text(candidate.get("market_key"), "").lower()
    if explicit_market_key:
        focuses.add(explicit_market_key)
    for key, aliases in _MARKET_FOCUS_ALIASES.items():
        if any(_text_has_market_alias(market_text, alias) for alias in aliases):
            focuses.add(key)
    fallback_market = _market_key_from_text(candidate.get("market"), allow_fallback=True)
    if fallback_market:
        focuses.add(fallback_market)
    return focuses


def _candidate_market_aliases(candidate: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    market_text = _safe_text(candidate.get("market"), "")
    normalized_market = _normalized_market_text(market_text)
    if normalized_market:
        aliases.add(normalized_market)
    for key in _candidate_market_focuses(candidate):
        aliases.add(_normalized_market_text(_market_label(key)))
        for alias in _MARKET_FOCUS_ALIASES.get(key, ()): 
            aliases.add(_normalized_market_text(alias))
    return {alias for alias in aliases if alias and alias not in _MARKET_FALLBACK_STOPWORDS}


def _resolved_requested_markets(
    question: str,
    candidates: list[dict[str, Any]],
    requested_markets: list[str] | tuple[str, ...] | None,
) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for item in requested_markets or []:
        key = str(item or "").strip().lower()
        if key and key not in seen:
            resolved.append(key)
            seen.add(key)

    normalized_question = _normalized_market_text(question)
    if not normalized_question:
        return resolved

    padded_question = f" {normalized_question} "
    for candidate in candidates:
        candidate_keys = sorted(_candidate_market_focuses(candidate))
        if not candidate_keys:
            continue
        aliases = _candidate_market_aliases(candidate)
        if not aliases:
            continue
        if not any(f" {alias} " in padded_question for alias in aliases):
            continue
        for key in candidate_keys:
            if key not in seen:
                resolved.append(key)
                seen.add(key)
    if "total_bases" in seen and "total" in seen:
        resolved = [key for key in resolved if key != "total"]
    return resolved


def _filter_candidates_to_requested_markets(
    candidates: list[dict[str, Any]],
    requested_markets: list[str] | tuple[str, ...] | None,
) -> list[dict[str, Any]]:
    requested_market_set = {str(item).strip().lower() for item in (requested_markets or []) if str(item).strip()}
    if not requested_market_set:
        return list(candidates)
    return [row for row in candidates if _candidate_market_focuses(row) & requested_market_set]


def _preferred_market_focus(candidate: dict[str, Any], preferences: dict[str, Any]) -> str | None:
    candidate_focuses = _candidate_market_focuses(candidate)
    if not candidate_focuses:
        return None
    requested_markets = [str(item).strip().lower() for item in (preferences.get("requested_markets") or []) if str(item).strip()]
    for key in requested_markets:
        if key in candidate_focuses:
            return key
    return sorted(candidate_focuses)[0] if candidate_focuses else None


def _candidate_selection_direction(candidate: dict[str, Any]) -> int:
    selection_text = _normalized_market_text(
        " ".join(
            [
                _safe_text(candidate.get("pick"), ""),
                _safe_text(candidate.get("name"), ""),
            ]
        )
    )
    if " under " in f" {selection_text} ":
        return -1
    if " over " in f" {selection_text} ":
        return 1
    return 0


def _candidate_subject_key(candidate: dict[str, Any]) -> str | None:
    if _safe_text(candidate.get("candidate_type"), "candidate") != "prop":
        return None
    name_text = _normalized_market_text(_safe_text(candidate.get("name"), ""))
    if not name_text:
        return None
    for marker in (" over ", " under "):
        if marker in f" {name_text} ":
            subject = name_text.split(marker, 1)[0].strip()
            return subject or None
    pick_text = _normalized_market_text(_safe_text(candidate.get("pick"), ""))
    if pick_text and name_text.endswith(pick_text):
        subject = name_text[: -len(pick_text)].strip()
        if subject:
            return subject
    return None


def _candidate_subject_aliases(candidate: dict[str, Any]) -> set[str]:
    subject_key = _candidate_subject_key(candidate)
    if not subject_key:
        return set()
    aliases = {subject_key}
    parts = [part for part in subject_key.split() if part]
    if len(parts) >= 2:
        aliases.add(parts[-1])
    if len(parts) >= 3:
        aliases.add(" ".join(parts[-2:]))
    return {alias for alias in aliases if len(alias) >= 3}


def _resolved_requested_subjects(question: str, candidates: list[dict[str, Any]]) -> list[str]:
    normalized_question = _normalized_market_text(question)
    if not normalized_question:
        return []
    matches: list[tuple[int, str]] = []
    seen: set[str] = set()
    question_tokens = normalized_question.split()

    def fuzzy_subject_position(aliases: set[str]) -> int | None:
        best_position: int | None = None
        best_score = 0.0
        for alias in aliases:
            alias_tokens = alias.split()
            if len(alias_tokens) < 2:
                continue
            window_size = len(alias_tokens)
            for index in range(0, len(question_tokens) - window_size + 1):
                window_text = " ".join(question_tokens[index : index + window_size])
                score = SequenceMatcher(None, window_text, alias).ratio()
                if score >= 0.88 and score > best_score:
                    best_score = score
                    best_position = index
        return best_position

    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        subject_key = _candidate_subject_key(candidate)
        if not subject_key or subject_key in seen:
            continue
        for alias in sorted(_candidate_subject_aliases(candidate), key=len, reverse=True):
            match = re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalized_question)
            if not match:
                continue
            seen.add(subject_key)
            matches.append((match.start(), subject_key))
            break
        if subject_key in seen:
            continue
        fuzzy_position = fuzzy_subject_position(_candidate_subject_aliases(candidate))
        if fuzzy_position is not None:
            seen.add(subject_key)
            matches.append((fuzzy_position, subject_key))
    return [subject for _, subject in sorted(matches, key=lambda item: item[0])]


def _display_subject_names(candidates: list[dict[str, Any]], subject_keys: list[str] | tuple[str, ...] | None) -> list[str]:
    """Map lowercase subject keys back to display-cased names.

    parsed_request is a public, UI-facing field; its subjects should read
    "Aaron Judge", not the lowercase matching key. The candidate's own name
    carries the real casing (naive title-casing breaks McCutchen, O'Neill),
    so resolve through the pool and only fall back to capitalization for a
    key no candidate carries.
    """
    display_by_key: dict[str, str] = {}
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        key = _candidate_subject_key(candidate)
        if not key or key in display_by_key:
            continue
        name_text = _safe_text(candidate.get("name"), "")
        lowered = name_text.lower()
        for marker in (" over ", " under "):
            if marker in f" {lowered} ":
                cut = lowered.index(marker.strip())
                display_by_key[key] = name_text[:cut].strip()
                break
        else:
            display_by_key[key] = name_text.strip() or key
    return [
        display_by_key.get(key, " ".join(part.capitalize() for part in str(key).split()))
        for key in (subject_keys or [])
        if str(key).strip()
    ]


def _filter_candidates_to_requested_subjects(
    candidates: list[dict[str, Any]],
    requested_subjects: list[str] | tuple[str, ...] | None,
) -> list[dict[str, Any]]:
    wanted = {str(item).strip().lower() for item in (requested_subjects or []) if str(item).strip()}
    if not wanted:
        return candidates
    filtered = [candidate for candidate in candidates if (_candidate_subject_key(candidate) or "") in wanted]
    return filtered or candidates


def _candidate_team_key(candidate: dict[str, Any]) -> str | None:
    for field in ("team_key", "team", "team_abbr", "team_slug", "player_team"):
        value = _normalized_market_text(_safe_text(candidate.get(field), ""))
        if value:
            return value
    return None


def _candidate_market_margin(candidate: dict[str, Any]) -> tuple[float | None, float | None]:
    live_projection = _numeric_hint(candidate.get("live_projection"))
    projected_value = live_projection if live_projection is not None else _numeric_hint(candidate.get("projected"))
    line_value = _numeric_hint(candidate.get("line"))
    if projected_value is None or line_value is None:
        return (None, None)
    direction = _candidate_selection_direction(candidate)
    margin = projected_value - line_value
    if direction < 0:
        margin *= -1.0
    elif direction == 0:
        margin = abs(margin)
    scale_base = max(abs(line_value), 1.0)
    return (margin, margin / scale_base)


def _candidate_market_fit(candidate: dict[str, Any], market_context: dict[str, Any]) -> dict[str, Any]:
    market_keys = sorted(_candidate_market_focuses(candidate))
    market_key = market_keys[0] if market_keys else _market_key_from_text(candidate.get("market"), allow_fallback=True)
    candidate_type = _safe_text(candidate.get("candidate_type"), "candidate")
    sport_slug = _safe_text(candidate.get("sport_slug"), "").lower() or None
    profile = _market_shape_profile(market_key, candidate_type=candidate_type, sport_slug=sport_slug)
    margin, normalized_margin = _candidate_market_margin(candidate)
    price_edge_pct = market_context.get("price_edge_pct")
    confidence_pct = _pct_hint(candidate.get("confidence"))
    fit_score = 0.0
    note_parts: list[str] = []
    if margin is not None:
        fit_score += min(max(0.0, margin), float(profile["margin_cap"])) * float(profile["margin_weight"])
        note_parts.append(f"Projection gap {margin:+.2f} versus the current line")
    if normalized_margin is not None:
        fit_score += min(max(0.0, normalized_margin), float(profile["normalized_margin_cap"])) * float(profile["normalized_margin_weight"])
    if price_edge_pct is not None:
        fit_score += max(-5.0, min(6.0, float(price_edge_pct) * float(profile["price_edge_weight"])))
        note_parts.append(f"model-versus-price edge {float(price_edge_pct):+.2f} pts")
    else:
        edge_pct = _pct_hint(candidate.get("edge"))
        if edge_pct is not None:
            fit_score += max(-5.0, min(6.0, float(edge_pct) * float(profile["edge_weight"])))
            note_parts.append(f"stored edge {float(edge_pct):+.2f}%")
    if confidence_pct is not None:
        fit_score += max(
            -3.0,
            min(4.0, (float(confidence_pct) - float(profile["confidence_baseline"])) * float(profile["confidence_weight"])),
        )
    shape_note = str(profile.get("shape_detail") or profile["shape"]).replace("_", " ")
    note_parts.append(f"shape {shape_note}")
    return {
        "market_key": market_key,
        "market_label": _market_label(market_key),
        "market_shape": profile["shape"],
        "market_shape_detail": profile.get("shape_detail") or profile["shape"],
        "market_fit_score": round(fit_score, 2),
        "market_fit_note": "; ".join(note_parts) if note_parts else None,
    }


def _market_specific_score_adjustment(candidate: dict[str, Any], preferences: dict[str, Any], market_context: dict[str, Any]) -> float:
    requested_markets = [str(item).strip().lower() for item in (preferences.get("requested_markets") or []) if str(item).strip()]
    if not requested_markets:
        return 0.0
    focus = _preferred_market_focus(candidate, preferences)
    if focus is None:
        return 0.0
    margin, normalized_margin = _candidate_market_margin(candidate)
    candidate_type = _safe_text(candidate.get("candidate_type"), "candidate")
    sport_slug = _safe_text(candidate.get("sport_slug"), "").lower() or None
    profile = _market_shape_profile(focus, candidate_type=candidate_type, sport_slug=sport_slug)
    confidence_pct = _pct_hint(candidate.get("confidence")) or 0.0
    edge_pct = _pct_hint(candidate.get("edge"))
    if edge_pct is None:
        edge_pct = float(market_context.get("price_edge_pct") or 0.0)
    price_edge_pct = market_context.get("price_edge_pct")
    american_odds = market_context.get("american_odds")

    adjustment = 0.0
    if margin is not None:
        adjustment += min(max(0.0, margin), float(profile["margin_cap"])) * float(profile["margin_weight"])
    if normalized_margin is not None:
        adjustment += min(max(0.0, normalized_margin), float(profile["normalized_margin_cap"])) * float(profile["normalized_margin_weight"])
    if candidate_type == "game" and price_edge_pct is not None:
        adjustment += max(0.0, float(price_edge_pct)) * float(profile["price_edge_weight"])
    adjustment += max(0.0, float(edge_pct)) * float(profile["edge_weight"])
    adjustment += max(0.0, confidence_pct - float(profile["confidence_baseline"])) * float(profile["confidence_weight"])
    if candidate_type == "game" and preferences.get("live_only") and bool(candidate.get("is_live")):
        adjustment += 4.0
    if candidate_type != "game" and american_odds is not None and float(american_odds) >= 100.0 and float(price_edge_pct or 0.0) > 0.0:
        adjustment += float(profile["plus_money_bonus"])
    return round(adjustment, 3)


def _risk_profile_score_adjustment(candidate: dict[str, Any], preferences: dict[str, Any], market_context: dict[str, Any]) -> float:
    risk_profile = _safe_text(preferences.get("risk_profile"), "balanced").lower()
    if risk_profile not in {"conservative", "aggressive"}:
        return 0.0

    confidence_pct = _pct_hint(candidate.get("confidence")) or 0.0
    edge_pct = market_context.get("price_edge_pct")
    if edge_pct is None:
        edge_pct = _pct_hint(candidate.get("edge")) or 0.0
    american_odds = market_context.get("american_odds")
    market_key = _candidate_market_key(candidate)
    candidate_type = _safe_text(candidate.get("candidate_type"), "candidate")

    adjustment = 0.0
    if risk_profile == "conservative":
        adjustment += min(4.5, max(0.0, float(confidence_pct) - 54.0) * 0.24)
        adjustment += min(2.5, max(0.0, float(edge_pct)) * 0.14)
        if american_odds is not None and float(american_odds) >= 100.0:
            adjustment -= min(3.5, (float(american_odds) - 100.0) / 60.0)
        if candidate_type != "game" and market_key in _BINARY_CEILING_MARKETS:
            adjustment -= 1.75
        return round(adjustment, 3)

    if american_odds is not None and float(american_odds) >= 100.0:
        adjustment += min(4.5, (float(american_odds) - 100.0) / 55.0)
    elif american_odds is not None and float(american_odds) < 0.0:
        adjustment -= min(1.5, abs(float(american_odds)) / 220.0)
    adjustment += min(2.5, max(0.0, float(edge_pct)) * 0.16)
    if candidate_type != "game" and market_key in _BINARY_CEILING_MARKETS:
        adjustment += 1.75
    if confidence_pct > 0.0:
        adjustment -= min(1.5, max(0.0, 55.0 - float(confidence_pct)) * 0.04)
    return round(adjustment, 3)


def _candidate_market_key(candidate: dict[str, Any]) -> str | None:
    market_focuses = sorted(_candidate_market_focuses(candidate))
    if market_focuses:
        return market_focuses[0]
    combined = " ".join(
        [
            _safe_text(candidate.get("market"), ""),
            _safe_text(candidate.get("pick"), ""),
            _safe_text(candidate.get("name"), ""),
        ]
    )
    return _market_key_from_text(combined, allow_fallback=True)


def _candidate_matches_requested_markets(candidate: dict[str, Any], preferences: dict[str, Any]) -> bool:
    requested_markets = [str(key).strip().lower() for key in (preferences.get("requested_markets") or []) if str(key).strip()]
    if not requested_markets:
        return True
    return bool(_candidate_market_focuses(candidate) & set(requested_markets))


def _candidate_has_required_fields(candidate: dict[str, Any]) -> bool:
    sport_slug = _safe_text(candidate.get("sport_slug"), _safe_text(candidate.get("sport"), "")).lower()
    market = _safe_text(candidate.get("market"), _safe_text(candidate.get("market_key"), ""))
    matchup = _safe_text(candidate.get("matchup"), _safe_text(candidate.get("event_id"), _safe_text(candidate.get("game_id"), "")))
    subject = _safe_text(
        candidate.get("name"),
        _safe_text(
            candidate.get("pick"),
            _safe_text(candidate.get("selection"), _safe_text(candidate.get("player_name"), _safe_text(candidate.get("team"), ""))),
        ),
    )
    if not sport_slug or not market or not matchup:
        return False
    if _safe_text(candidate.get("candidate_type"), "candidate") == "game":
        return True
    return bool(subject)


def _candidate_value_is_present(value: Any) -> bool:
    """Whether a normalized candidate field actually carries a value.

    #68. This existed as `value is not None and _safe_text(value, "") not in
    {"", "-"}`, and `_safe_text` is truthiness-based (`str(value or "")`), so
    **numeric zero read as missing**: `_safe_text(0.0, "")` is `""`. A
    candidate whose projection is 0.0 was therefore rejected as
    `missing_projection_or_odds`.

    That is not hypothetical. A live game-level candidate with no explicit
    live_projection gets `_game_current_combined_score(game)` instead
    ([home.py](../../blueprints/home.py) `_append_game_bet_candidate`), which
    is **0 for every scoreless live game** -- and normalize_candidate takes the
    first *present* field in its scan order, so that 0 also shadows any real
    model_probability/fair_probability/edge further down the list. Measured
    against production 2026-07-26: all 32 live MLS game candidates were pruned
    this way. `_candidate_has_usable_projection` used to be a second,
    isinstance-correct copy of this same question with zero callers anywhere
    in the codebase -- removed as dead code during #100's consolidation pass
    rather than left as a second implementation nothing used or kept in sync.

    Keeps rejecting None, "" and "-", so a genuinely absent field is still
    absent.
    """
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return _safe_text(value, "") not in {"", "-"}


def _classify_candidate_with_reason(candidate: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    # Single source of truth for candidate validity: classify_candidate() and
    # _candidate_classification_removal_reason() used to be two independently
    # maintained implementations of this same predicate, and the reason-only
    # copy had already drifted into a hand-approximated superset rather than a
    # true mirror. Both are now thin wrappers around this.
    normalized = normalize_candidate(candidate)
    if not _safe_text(normalized.get("selection"), ""):
        return None, "missing_selection"
    if not _safe_text(normalized.get("type"), ""):
        return None, "missing_type"
    has_projection = _candidate_value_is_present(normalized.get("projection"))
    has_odds = _candidate_value_is_present(normalized.get("odds"))
    if not (has_projection or has_odds):
        return None, "missing_projection_or_odds"
    source_strength = _numeric_hint(normalized.get("source_strength"))
    tier = "tier_1" if has_projection and has_odds and source_strength is not None and float(source_strength) > 0.7 else "tier_2"
    normalized["tier"] = tier
    return normalized, None


def classify_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    classified, _reason = _classify_candidate_with_reason(candidate)
    return classified


def _candidate_is_source_backed(candidate: dict[str, Any]) -> bool:
    classified = classify_candidate(candidate)
    return bool(classified and classified.get("tier") == "tier_1")


def normalize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(candidate) if isinstance(candidate, Mapping) else {}
    sport = _safe_text(normalized.get("sport"), _safe_text(normalized.get("sport_slug"), "sport"))
    sport_slug = _safe_text(normalized.get("sport_slug"), sport).lower()
    candidate_type = _safe_text(normalized.get("type"), _safe_text(normalized.get("candidate_type"), ""))
    if candidate_type not in {"game", "prop", "parlay"}:
        candidate_type = _safe_text(normalized.get("candidate_type"), "prop").lower()
    if candidate_type not in {"game", "prop", "parlay"}:
        candidate_type = "prop"
    selection = _safe_text(
        normalized.get("selection"),
        _safe_text(normalized.get("pick"), _safe_text(normalized.get("name"), "")),
    ) or None
    market = _safe_text(normalized.get("market"), _safe_text(normalized.get("market_key"), "")) or None
    odds = normalized.get("odds")
    if _safe_text(odds, "") in {"", "-"}:
        odds = None
    projection = normalized.get("projection")
    if projection is None:
        for field in ("projected", "live_projection", "live_total", "expected_value", "adjusted_edge", "edge", "model_probability", "fair_probability"):
            value = normalized.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                projection = float(value)
                break
            if field in {"projected", "live_projection", "live_total"} and _safe_text(value, "") not in {"", "-"}:
                try:
                    projection = float(str(value).strip())
                except Exception:
                    projection = value
                break
    source = _safe_text(normalized.get("source"), "") or None
    source_strength = _numeric_hint(normalized.get("source_strength"))
    if source_strength is None:
        source_strength = 0.5
    normalized.update(
        {
            "sport": sport or sport_slug.upper(),
            "sport_slug": sport_slug,
            "type": candidate_type,
            "candidate_type": normalized.get("candidate_type") or candidate_type,
            "selection": selection,
            "market": market,
            "odds": odds,
            "projection": projection if projection is not None else None,
            "source": source,
            "source_strength": max(0.0, min(1.0, float(source_strength))),
            "is_live": bool(normalized.get("is_live")),
        }
    )
    return normalized


def is_valid_candidate(candidate: dict[str, Any]) -> bool:
    return classify_candidate(candidate) is not None


def _apply_candidate_tier_penalty(candidate: dict[str, Any]) -> dict[str, Any]:
    classified = classify_candidate(candidate)
    if classified is None:
        return candidate
    candidate.update(classified)
    if candidate.get("tier") != "tier_2":
        return candidate
    score_value = _numeric_hint(candidate.get("score"))
    if score_value is not None:
        candidate["score"] = round(max(0.0, float(score_value) - 3.0), 4)
    adjusted_score_value = _numeric_hint(candidate.get("adjusted_score"))
    if adjusted_score_value is not None:
        candidate["adjusted_score"] = round(max(0.0, float(adjusted_score_value) - 3.0), 4)
    return candidate


def _prop_dupe_line_token(value: Any) -> str:
    if value in (None, "", "-"):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _safe_text(value, "").strip().lower()
    if number.is_integer():
        return str(int(number))
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _prop_candidate_has_player_identity(candidate: Mapping[str, Any]) -> bool:
    team_tokens = {
        _safe_text(candidate.get("team"), "").strip().lower(),
        _safe_text(candidate.get("home_team"), "").strip().lower(),
        _safe_text(candidate.get("away_team"), "").strip().lower(),
    }
    team_tokens.discard("")
    for field in ("entity", "player_name", "player"):
        value = _safe_text(candidate.get(field), "").strip().lower()
        if value and value not in team_tokens:
            return True
    return False


def _drop_entityless_prop_duplicates(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # 2026-07-23: two pipelines can independently produce a candidate for the
    # same underlying player prop -- one correctly attributed to the player,
    # the other with the player identity missing/blank (root cause traced to
    # a row-builder that leaves player_name blank rather than always
    # resolving it). Rather than serve both as a visible duplicate, or guess
    # which is "more correct", prefer whichever sibling actually carries a
    # player identity for the same sport/matchup/market/line and drop the
    # rest. Deliberately does not key on game_pk: the entity-less duplicate
    # is often missing it entirely.
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for candidate in candidates:
        if _safe_text(candidate.get("candidate_type"), "") != "prop":
            continue
        key = (
            _safe_text(candidate.get("sport_slug"), "sport"),
            _safe_text(candidate.get("matchup"), "matchup"),
            _safe_text(candidate.get("market"), "market"),
            _prop_dupe_line_token(candidate.get("line")),
        )
        groups.setdefault(key, []).append(candidate)

    dropped_ids: set[int] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        if not any(_prop_candidate_has_player_identity(c) for c in group):
            continue
        for candidate in group:
            if not _prop_candidate_has_player_identity(candidate):
                dropped_ids.add(id(candidate))

    if not dropped_ids:
        return candidates, []
    kept = [c for c in candidates if id(c) not in dropped_ids]
    dropped = [c for c in candidates if id(c) in dropped_ids]
    return kept, dropped


def _primary_query_candidates(
    overview: list[dict[str, Any]],
    preferences: dict[str, Any],
    odds_history_by_sport: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return collect_candidates(overview, preferences, odds_history_by_sport)


def _collect_candidates(overview: list[dict[str, Any]], preferences: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    question_text = _safe_text(preferences.get("question"), "").lower()
    wants_mlb_hr_targets = preferences.get("analysis_focus") == "mlb_home_runs" or "home_runs" in {
        str(item).strip().lower() for item in (preferences.get("requested_markets") or []) if str(item).strip()
    }
    wants_ranked_mlb_market_backfill = bool(
        re.search(r"\b(?:top|best)\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b", question_text)
    )
    for sport in overview:
        if not isinstance(sport, dict) or not _sport_matches_preferences(sport, preferences):
            continue
        sport_started_at = time.perf_counter()
        sport_start_count = len(candidates)
        sport_slug = _safe_text(sport.get("slug"), "").lower()
        sport_health = _safe_text(sport.get("data_health"), "").lower()
        dashboard_games = sport.get("dashboard_games") if isinstance(sport.get("dashboard_games"), list) else []
        home_rails = sport.get("home_rails") if isinstance(sport.get("home_rails"), dict) else {}
        if preferences.get("include_props"):
            pregame_candidates: list[dict[str, Any]] = []
            pregame = home_rails.get("pregame") if isinstance(home_rails.get("pregame"), dict) else {}
            for item in pregame.get("items") or []:
                if isinstance(item, dict):
                    candidate = _prop_candidate_from_item(
                        sport,
                        item,
                        surface_key="pregame",
                        surface_title=_safe_text(pregame.get("title"), "Pregame props"),
                    )
                    if candidate is None:
                        continue
                    candidates.append(candidate)
                    pregame_candidates.append(candidate)
            if pregame_candidates:
                _log_candidate_stage(pipeline_name="collect_candidates", stage="pregame_prop_candidate_creation", before=[], after=pregame_candidates)
            live_candidates: list[dict[str, Any]] = []
            live = home_rails.get("live") if isinstance(home_rails.get("live"), dict) else {}
            for item in live.get("items") or []:
                if isinstance(item, dict):
                    candidate = _prop_candidate_from_item(
                        sport,
                        item,
                        surface_key="live",
                        surface_title=_safe_text(live.get("title"), "Top Live Props"),
                    )
                    if candidate is None:
                        continue
                    candidates.append(candidate)
                    live_candidates.append(candidate)
            if live_candidates:
                _log_candidate_stage(pipeline_name="collect_candidates", stage="live_prop_candidate_creation", before=[], after=live_candidates)
        if preferences.get("include_games"):
            game_candidates = _game_candidates_for_sport(sport)
            candidates.extend(game_candidates)
            if game_candidates:
                _log_candidate_stage(pipeline_name="collect_candidates", stage="game_candidate_creation", before=[], after=game_candidates)
        # Steam moves as real board candidates, per explicit user direction:
        # every sport, unconditionally (gated only on the same
        # props-or-games-requested check every other sport-agnostic block
        # above uses -- "top edges today"'s own default resolves both True,
        # see the include_props/include_games derivation above), not behind
        # a question-text heuristic. Both lanes: _steam_candidates_for_sport
        # tags each event "live"/"pregame" from the detector's own
        # capture_phase/is_live fields, so the existing LIVE/PREGAME state
        # filter and a new steam-only filter both work on these unmodified.
        if preferences.get("include_props") or preferences.get("include_games"):
            steam_candidates = _steam_candidates_for_sport(sport)
            candidates.extend(steam_candidates)
            if steam_candidates:
                _log_candidate_stage(pipeline_name="collect_candidates", stage="steam_candidate_creation", before=[], after=steam_candidates)
        if wants_mlb_hr_targets:
            hr_candidates = _mlb_home_run_candidates_from_artifact(sport)
            candidates.extend(hr_candidates)
            if hr_candidates:
                _log_candidate_stage(pipeline_name="collect_candidates", stage="mlb_home_run_backfill", before=[], after=hr_candidates)
        if _safe_text(sport.get("slug"), "").lower() == "mlb":
            # _mlb_subject_prop_candidates_from_artifact was defined
            # (matches a top-props artifact row's player name against the
            # question, independent of the "top N"/explicit-market phrasing
            # wants_ranked_mlb_market_backfill requires) but never called --
            # "What does Brandon Young's matchup look like" named no market
            # and no "top N", so a real subject question with data sitting
            # in the artifact still produced zero candidates. It already
            # self-gates on a whole-word match against the question, so this
            # is a no-op for every query that doesn't name a rostered player.
            subject_prop_candidates = _mlb_subject_prop_candidates_from_artifact(
                sport, question=_safe_text(preferences.get("question"), ""), preferences=preferences
            )
            candidates.extend(subject_prop_candidates)
            if subject_prop_candidates:
                _log_candidate_stage(pipeline_name="collect_candidates", stage="mlb_subject_prop_backfill", before=[], after=subject_prop_candidates)
            # #128: unconditional, not gated behind a question-text heuristic
            # like the other MLB backfills above -- daily_top_props is a
            # once-a-day snapshot, live-lens rotates continuously, and a live
            # prop that only ever exists in live-lens must still be able to
            # become a board candidate. In-pool dedup below (same
            # subject/market/pick already present) prevents a duplicate for
            # anything daily_top_props/subject-prop backfill already added.
            live_lens_prop_candidates: list[dict[str, Any]] = []
            for artifact_candidate in _mlb_live_lens_prop_candidates_from_artifact(sport):
                artifact_subject = _candidate_subject_key(artifact_candidate)
                artifact_market = _candidate_market_key(artifact_candidate)
                artifact_pick = _safe_text(artifact_candidate.get("pick"), "")
                existing_match = next(
                    (
                        existing
                        for existing in candidates
                        if _candidate_subject_key(existing) == artifact_subject
                        and _candidate_market_key(existing) == artifact_market
                        and _safe_text(existing.get("pick"), "") == artifact_pick
                    ),
                    None,
                )
                if existing_match is not None:
                    # Root-caused 2026-07-31 against real production data:
                    # this used to silently drop the fresh, correctly-live
                    # live-lens candidate in favor of whichever stale
                    # home_rails/dashboard candidate for the same
                    # subject/market/pick was already in the pool -- the
                    # same live gamePk produced a mix of correctly-"live"
                    # and incorrectly-"Pre-Game" rows depending purely on
                    # insertion order. The live-lens artifact row is always
                    # the freshest available data for a live game (it's
                    # rebuilt continuously and hardcodes is_live=True when
                    # reached, see the #128 comment above), so merge its
                    # live-relevant fields into the existing candidate in
                    # place rather than discarding it -- preserves the
                    # existing candidate's position/identity for anything
                    # downstream that depends on it, while fixing the
                    # is_live/status_display/game_state/actual mismatch.
                    for key in ("is_live", "is_final", "status_display", "game_state", "actual", "live_projection"):
                        if artifact_candidate.get(key) is not None:
                            existing_match[key] = artifact_candidate[key]
                    continue
                candidates.append(artifact_candidate)
                live_lens_prop_candidates.append(artifact_candidate)
            if live_lens_prop_candidates:
                _log_candidate_stage(pipeline_name="collect_candidates", stage="mlb_live_lens_prop_backfill", before=[], after=live_lens_prop_candidates)
        if sport_slug == "soccer":
            # Soccer's own live-lens-prop mirror of the MLB backfill above.
            # Confirmed live 2026-08-01: _SoccerDataProvider.live_props()
            # (syndicate/blueprints/home.py) is hardcoded `return []` --
            # soccer has never produced a single live prop candidate on the
            # Layer 2 board, regardless of how many real live matches are in
            # progress. Same unconditional/dedup-merge shape as MLB's block
            # above, just against soccer's live_state artifact (already
            # ticking on its own ~60s live-lens loop, see
            # scripts/poll_soccer_live_state.py) instead of MLB's live-lens
            # report.
            soccer_live_lens_candidates: list[dict[str, Any]] = []
            for artifact_candidate in _soccer_live_lens_prop_candidates_from_artifact(sport):
                artifact_subject = _candidate_subject_key(artifact_candidate)
                artifact_market = _candidate_market_key(artifact_candidate)
                artifact_pick = _safe_text(artifact_candidate.get("pick"), "")
                existing_match = next(
                    (
                        existing
                        for existing in candidates
                        if _candidate_subject_key(existing) == artifact_subject
                        and _candidate_market_key(existing) == artifact_market
                        and _safe_text(existing.get("pick"), "") == artifact_pick
                    ),
                    None,
                )
                if existing_match is not None:
                    for key in ("is_live", "is_final", "status_display", "game_state", "actual", "live_projection"):
                        if artifact_candidate.get(key) is not None:
                            existing_match[key] = artifact_candidate[key]
                    continue
                candidates.append(artifact_candidate)
                soccer_live_lens_candidates.append(artifact_candidate)
            if soccer_live_lens_candidates:
                _log_candidate_stage(pipeline_name="collect_candidates", stage="soccer_live_lens_prop_backfill", before=[], after=soccer_live_lens_candidates)
        if wants_ranked_mlb_market_backfill:
            backfill_candidates: list[dict[str, Any]] = []
            for artifact_candidate in _mlb_market_prop_candidates_from_artifact(sport, preferences):
                artifact_subject = _candidate_subject_key(artifact_candidate)
                artifact_market = _candidate_market_key(artifact_candidate)
                artifact_pick = _safe_text(artifact_candidate.get("pick"), "")
                if any(
                    _candidate_subject_key(existing) == artifact_subject
                    and _candidate_market_key(existing) == artifact_market
                    and _safe_text(existing.get("pick"), "") == artifact_pick
                    for existing in candidates
                ):
                    continue
                candidates.append(artifact_candidate)
                backfill_candidates.append(artifact_candidate)
            if backfill_candidates:
                _log_candidate_stage(pipeline_name="collect_candidates", stage="mlb_market_backfill", before=[], after=backfill_candidates)
        if sport_slug == "mlb":
            # 2026-08-02 board audit follow-up: found a class of MLB prop
            # candidate (confirmed live: "Miguel Rojas"/pick "OVER Miguel
            # Rojas", narrative "detail" with the real mean baked into
            # prose -- "...baseline comes in around 1.8 batter hits runs
            # rbis...") whose exact originating builder could not be
            # pinned down despite tracing through every known MLB
            # candidate source (home_rails pregame/live rails, daily_top_
            # props direct reads, live-lens, steam) -- it isn't gated
            # behind wants_ranked_mlb_market_backfill above (that only
            # fires when the question names a specific market; "top edges
            # today" doesn't), so it never gets a correctly-labeled
            # artifact-style duplicate in the pool for
            # _merge_duplicate_prop_candidates to backfill from, even
            # though the row it's built from (confirmed: rank 39, well
            # outside the home rail's own top-18 cap) has a real mean
            # sitting right there. Rather than risk a change to whichever
            # function builds it, backfill "projected" directly on any
            # MLB prop candidate that's missing it, reusing the exact same
            # pregame-mean lookup _mlb_live_lens_prop_candidates_from_
            # artifact already relies on -- blank-only, so it can never
            # overwrite a real value, and it does nothing for a candidate
            # with no resolvable subject+market+game match.
            filled_count = _mlb_backfill_missing_projected_from_top_props(sport, candidates[sport_start_count:])
            if filled_count:
                _log_candidate_stage(pipeline_name="collect_candidates", stage="mlb_missing_projected_backfill", before=[], after=candidates[sport_start_count:])
        sport_candidates = candidates[sport_start_count:]
        sport_market_counts: dict[str, int] = {}
        for candidate in sport_candidates:
            market_key = _safe_text(candidate.get("candidate_type") or candidate.get("type"), "candidate").lower() or "candidate"
            sport_market_counts[market_key] = sport_market_counts.get(market_key, 0) + 1
        _intel_trace_timed(
            "candidate_generation",
            sport_started_at,
            sport=sport_slug,
            context_label=_safe_text(sport.get("context_label"), ""),
            generated=len(sport_candidates),
            markets=sport_market_counts,
        )

    before_merge_count = len(candidates)
    candidates = _merge_duplicate_prop_candidates(candidates)
    if len(candidates) != before_merge_count:
        _log_candidate_stage(pipeline_name="collect_candidates", stage="prop_duplicate_merge", before=[], after=candidates)

    before_game_side_merge_count = len(candidates)
    candidates = _merge_duplicate_game_side_candidates(candidates)
    if len(candidates) != before_game_side_merge_count:
        _log_candidate_stage(pipeline_name="collect_candidates", stage="game_side_duplicate_merge", before=[], after=candidates)

    stage_started_at = time.perf_counter()
    odds_history_by_sport = _odds_history_payloads_by_sport(overview)
    candidates = _enrich_candidates_with_odds_history(candidates, odds_history_by_sport)
    _log_candidate_stage(pipeline_name="collect_candidates", stage="post_odds_enrichment", before=[], after=candidates)

    _intel_trace_timed("candidate_generation", stage_started_at, stage="post_odds_enrichment", total_candidates=len(candidates))
    stage_started_at = time.perf_counter()
    validated_candidates: list[dict[str, Any]] = []
    state_pruned_candidates: list[dict[str, Any]] = []
    pruned_by_sport: dict[str, dict[str, int]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            state_pruned_candidates.append({"stage": "post_state_filter", "reason": "non_dict_candidate"})
            continue
        _apply_candidate_state_guard(candidate)
        if bool(candidate.get("state_invalid")):
            reason = _safe_text(candidate.get("state_note"), "state_invalid")
            state_pruned_candidates.append(_collect_candidate_trace(candidate, reason=reason, stage="post_state_filter"))
            sport_bucket = pruned_by_sport.setdefault(_safe_text(candidate.get("sport_slug"), "unknown").lower(), {})
            sport_bucket[reason] = sport_bucket.get(reason, 0) + 1
            continue
        validated_candidates.append(candidate)
    candidates = validated_candidates
    _log_candidate_stage(pipeline_name="collect_candidates", stage="post_state_filter", before=[], after=candidates)
    for removed_candidate in state_pruned_candidates:
        _log_json_event(logging.INFO, "collect_candidates_pruned", pipeline="collect_candidates", **removed_candidate)
    if pruned_by_sport:
        # 2026-07-19: _log_json_event's INFO-level output wasn't reaching
        # production stdout (no matching lines found for a real prune event
        # this stage clearly caused per the surrounding candidate_generation
        # trace counts), which made an entire sport's candidates disappearing
        # here silent/undiagnosable. This prints unconditionally, same
        # convention as [INTEL_TRACE], so a repeat is always visible in raw
        # worker logs without relying on logging-level configuration.
        print(f"[INTEL_TRACE] {json.dumps({'event': 'post_state_filter_pruned', 'by_sport_reason': pruned_by_sport})}", flush=True)
    _intel_trace_timed("candidate_generation", stage_started_at, stage="post_state_filter", total_candidates=len(candidates))

    stage_started_at = time.perf_counter()
    _intel_trace_timed("candidate_generation", stage_started_at, stage="pre_requested_market_filter", total_candidates=len(candidates))
    requested_market_pruned: list[dict[str, Any]] = []
    requested_market_input = list(candidates)
    candidates = _filter_candidates_to_requested_markets(candidates, preferences.get("requested_markets") or [])
    for candidate in requested_market_input:
        if candidate not in candidates:
            requested_market_pruned.append(_collect_candidate_trace(candidate, reason="requested_market_mismatch", stage="post_requested_market_filter"))
    _log_candidate_stage(pipeline_name="collect_candidates", stage="post_requested_market_filter", before=[], after=candidates)
    for removed_candidate in requested_market_pruned:
        _log_json_event(logging.INFO, "collect_candidates_pruned", pipeline="collect_candidates", **removed_candidate)
    _intel_trace_timed("candidate_generation", stage_started_at, stage="post_requested_market_filter", total_candidates=len(candidates))

    normalized_candidates = [normalize_candidate(candidate) for candidate in candidates]
    _log_candidate_stage(pipeline_name="collect_candidates", stage="normalize_candidate", before=candidates, after=normalized_candidates)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    classified_candidates: list[dict[str, Any]] = []
    classification_pruned: list[dict[str, Any]] = []
    dedupe_pruned: list[dict[str, Any]] = []
    for row in sorted(normalized_candidates, key=lambda candidate: float(candidate.get("score") or 0.0), reverse=True):
        # #117: matchup alone ("CLE @ CIN") is identical for both games of a
        # same-day doubleheader, so without a real per-game identifier in
        # this tuple, the second game's candidate gets dropped here as a
        # "duplicate" of the first before it ever reaches scoring -- the
        # confirmed live cause of only one set of candidates existing for a
        # doubleheader matchup instead of two. game_identity is appended
        # (not substituted for matchup) only when a real per-game id is
        # present, so candidate types that never carry one (some prop paths)
        # keep the exact prior 5-field behavior rather than risk
        # under-deduping on an always-empty new field.
        game_identity = _safe_text(row.get("gamePk") or row.get("game_id") or row.get("event_id"), "")
        identity = (
            _safe_text(row.get("candidate_type"), "candidate"),
            _safe_text(row.get("sport_slug"), "sport"),
            _safe_text(row.get("matchup"), "matchup"),
            _safe_text(row.get("market"), "market"),
            _safe_text(row.get("pick") or row.get("name"), "pick"),
        ) + ((game_identity,) if game_identity else ())
        if identity in seen:
            dedupe_pruned.append(_collect_candidate_trace(row, reason="duplicate_identity", stage="deduplication"))
            continue
        seen.add(identity)
        classified_row = classify_candidate(row)
        if classified_row is None:
            classification_pruned.append(_collect_candidate_trace(row, reason=_candidate_classification_removal_reason(row), stage="candidate_classification"))
            continue
        classified_candidates.append(classified_row)
        deduped.append(classified_row)
    _log_candidate_stage(pipeline_name="collect_candidates", stage="classify_candidate", before=normalized_candidates, after=classified_candidates)
    _log_candidate_stage(pipeline_name="collect_candidates", stage="deduplication", before=classified_candidates, after=deduped)
    for removed_candidate in classification_pruned + dedupe_pruned:
        _log_json_event(logging.INFO, "collect_candidates_pruned", pipeline="collect_candidates", **removed_candidate)
    # #64. This is the last stage before the pool and the ONLY one that was
    # invisible in production. Every earlier stage emits an INTEL_TRACE (a
    # print, which Render keeps); classification and dedupe reported only
    # through _log_json_event at logging.INFO, and logger.info never reaches
    # Render's collector (#37). So a build could take 16 candidates through
    # every traced filter, drop all 16 here, and report candidate_count=0 with
    # no visible reason -- exactly what happened on 2026-07-26, and it cost an
    # hour of reading code to find a fact the logs should have stated.
    #
    # Reason counts, not per-candidate rows: the point is "which rule is
    # rejecting them", answerable at a glance, without emitting one line per
    # candidate on every cycle.
    classification_reasons: dict[str, int] = {}
    for removed_candidate in classification_pruned:
        reason = str(removed_candidate.get("reason") or "unknown")
        classification_reasons[reason] = classification_reasons.get(reason, 0) + 1
    _intel_trace(
        "candidate_generation",
        stage="post_dedupe_and_classify",
        total_candidates=len(deduped),
        normalized_in=len(normalized_candidates),
        classification_pruned=len(classification_pruned),
        dedupe_pruned=len(dedupe_pruned),
        classification_reasons=classification_reasons,
    )
    _log_candidate_stage(pipeline_name="collect_candidates", stage="post_dedupe_and_classify", before=[], after=deduped)

    deduped, entityless_prop_duplicates = _drop_entityless_prop_duplicates(deduped)
    for removed_candidate in entityless_prop_duplicates:
        _log_json_event(
            logging.INFO,
            "collect_candidates_pruned",
            pipeline="collect_candidates",
            **_collect_candidate_trace(removed_candidate, reason="entityless_prop_duplicate", stage="entityless_prop_duplicate_filter"),
        )
    _log_candidate_stage(pipeline_name="collect_candidates", stage="entityless_prop_duplicate_filter", before=[], after=deduped)

    return deduped


def _apply_advanced_context_to_candidates(
    candidates: list[dict[str, Any]],
    advanced_by_sport: dict[str, list[dict[str, Any]]],
    preferences: dict[str, Any],
    *,
    odds_payload_cache: dict[tuple[str, str], dict[str, Any] | None] | None = None,
) -> None:
    # build_simulation_engine_context_from_candidate falls back to its own
    # build_market_features() call when a candidate doesn't already carry
    # market_features -- true for every candidate here, since this runs
    # during scoring, before filter_candidates (recommendation_engine.py)
    # attaches market_features. Without a shared cache that re-reads and
    # re-parses the sport's whole odds-history shard payload from disk once
    # per candidate, same bug shape as the filter_candidates/rank_recommendations
    # fix -- confirmed in production 2026-07-24 as a major contributor to this
    # loop's ~1.3s/candidate cost, on top of the simulation itself. Caller
    # (score_candidate, via _score_candidates) passes a batch-scoped cache --
    # this function is invoked once PER CANDIDATE (a single-item list each
    # time), so a cache created here would never be reused across candidates.
    if odds_payload_cache is None:
        odds_payload_cache = {}
    for candidate in candidates:
        sport_slug = _safe_text(candidate.get("sport_slug"), "sport").lower()
        advanced_context = advanced_by_sport.get(sport_slug, [])
        readiness_summary = _advanced_readiness_summary(advanced_context)
        market_context = _market_context(candidate)
        market_focuses = sorted(_candidate_market_focuses(candidate))
        market_fit = _candidate_market_fit(candidate, market_context)
        statcast_profile = _candidate_mlb_statcast_profile(candidate)
        existing_signals = [signal for signal in (candidate.get("advanced_signals") or []) if isinstance(signal, dict)]
        existing_signal_keys = {_safe_text(signal.get("key"), "") for signal in existing_signals}
        inferred_signals = [
            signal
            for signal in _context_driven_advanced_signals(candidate, advanced_context)
            if _safe_text(signal.get("key"), "") not in existing_signal_keys
        ]
        candidate["advanced_context"] = advanced_context
        candidate["advanced_gate"] = readiness_summary
        candidate["market_context"] = market_context
        candidate["market_focuses"] = market_focuses
        candidate["market_fit"] = market_fit
        candidate["mlb_statcast_profile"] = statcast_profile
        artifact_features = candidate.get("artifact_features") if isinstance(candidate.get("artifact_features"), dict) else {}
        if artifact_features:
            candidate["artifact_features"] = dict(artifact_features)
            candidate["feature_coverage"] = dict(artifact_features.get("feature_coverage") or candidate.get("feature_coverage") or {})
        coverage_profile = build_feature_coverage_profile(candidate.get("feature_coverage") or (artifact_features.get("feature_coverage") if artifact_features else {}))
        if coverage_profile:
            candidate["model_confidence"] = candidate.get("confidence")
            candidate.update(coverage_profile)
            if candidate.get("coverage_adjusted_confidence") is not None:
                candidate["confidence"] = candidate.get("coverage_adjusted_confidence")
        simulation_context = build_simulation_engine_context_from_candidate(candidate, odds_payload_cache=odds_payload_cache)
        candidate["simulation"] = _SIMULATION_ENGINE.run_simulation(simulation_context)
        candidate["advanced_signals"] = inferred_signals + existing_signals
        signal_contributions, signal_contributions_top_positive, signal_contributions_top_negative = _candidate_signal_contributions(candidate)
        candidate["signal_contributions"] = signal_contributions
        candidate["signal_contributions_top_positive"] = signal_contributions_top_positive
        candidate["signal_contributions_top_negative"] = signal_contributions_top_negative
        candidate["advanced_signal_score"] = _candidate_advanced_signal_score(candidate)
        candidate["source_summary_score"] = _basketball_source_summary_score(candidate)
        edge_profile = _candidate_betting_edge_profile(candidate)
        if edge_profile is not None:
            candidate["expected_value"] = round(float(edge_profile["expected_value"]), 4)
            candidate["volatility"] = round(float(edge_profile["volatility"]), 4)
            candidate["volatility_score"] = round(float(edge_profile["volatility_score"]), 4)
            candidate["volatility_penalty"] = round(float(edge_profile["volatility_penalty"]), 4)
            candidate["adjusted_edge"] = round(float(edge_profile["adjusted_edge"]), 4)


def _candidate_betting_edge_components(candidate: dict[str, Any]) -> tuple[float, float, float] | None:
    profile = _candidate_betting_edge_profile(candidate)
    if profile is None:
        return None
    return profile["implied_probability"], profile["model_probability"], profile["edge"]


def _candidate_betting_edge_profile(candidate: dict[str, Any]) -> dict[str, Any] | None:
    implied_probability = odds_to_implied_probability(_american_odds_value(candidate.get("odds")))
    model_probability = _candidate_model_probability(candidate)
    if model_probability is None or implied_probability is None:
        return None

    edge = model_probability - implied_probability
    simulation = candidate.get("simulation") if isinstance(candidate.get("simulation"), dict) else {}
    distributions = simulation.get("probability_distributions") if isinstance(simulation.get("probability_distributions"), dict) else simulation.get("distribution")

    decimal_odds = _american_to_decimal(_american_odds_value(candidate.get("odds")))
    if decimal_odds is None:
        decimal_odds = 1.0

    win_probability = model_probability
    loss_probability = max(0.0, 1.0 - win_probability)
    push_probability = 0.0
    if isinstance(distributions, dict) and any(key in distributions for key in ("win", "loss", "push")):
        win_probability = _numeric_hint(distributions.get("win")) or win_probability
        push_probability = _numeric_hint(distributions.get("push")) or 0.0
        loss_probability = _numeric_hint(distributions.get("loss"))
        if loss_probability is None:
            loss_probability = max(0.0, 1.0 - win_probability - push_probability)

    win_return = decimal_odds - 1.0
    loss_return = -1.0
    push_return = 0.0
    expected_value = (win_probability * win_return) + (loss_probability * loss_return) + (push_probability * push_return)
    variance = (
        (win_probability * ((win_return - expected_value) ** 2))
        + (loss_probability * ((loss_return - expected_value) ** 2))
        + (push_probability * ((push_return - expected_value) ** 2))
    )
    volatility_score = 0.0 if variance <= 0.0 else min(1.0, variance / (variance + 1.0))
    volatility_penalty = min(0.5, volatility_score * 0.5)
    adjusted_edge = edge * (1.0 - volatility_penalty)

    return {
        "implied_probability": implied_probability,
        "model_probability": model_probability,
        "edge": edge,
        "expected_value": expected_value,
        "volatility": variance,
        "volatility_score": volatility_score,
        "volatility_penalty": volatility_penalty,
        "adjusted_edge": adjusted_edge,
    }


def _candidate_betting_rank_key(candidate: dict[str, Any]) -> tuple[bool, float, float, float, float]:
    # advanced_ready leads the tuple, matching build_intelligence_board_contract's
    # card sort (#73): a candidate whose advanced inputs are missing or
    # unpublished is less trustworthy than one whose inputs are ready,
    # regardless of raw edge -- that principle was only ever applied to the
    # board_contract cards. This function backs the flat recommendations
    # list (_balanced_recommendation_order, _greedy_low_correlation_selection)
    # and never weighed readiness at all, so "prioritize ready advanced
    # inputs" held for board cards but not for the served recommendations
    # list -- two rankings of the same candidates disagreeing on the same
    # stated priority.
    advanced_ready = bool((candidate.get("advanced_gate") or {}).get("ready"))
    # score leads edge/confidence, not the other way around: _score_candidates
    # folds edge, confidence, tier, AND the risk-profile/market-focus
    # adjustments into score (see the worked example above
    # _risk_profile_score_adjustment's call site) -- putting raw edge ahead
    # of it let a single unadjusted component outvote the composite exactly
    # the risk profile was computed to influence. Confirmed: a "highest
    # confidence" (-> conservative) query still ranked a 38%-confidence
    # +320 longshot above a 64%-confidence -135 favorite, because edge
    # (12.8% vs 2.5%) was compared before the correctly risk-adjusted score.
    # Same principle build_intelligence_board_contract's card sort (#73)
    # already applies; this function just hadn't caught up.
    score_value = _numeric_hint(candidate.get("score"))
    score = score_value if score_value is not None else float("-inf")
    profile = _candidate_betting_edge_profile(candidate)
    edge = profile["adjusted_edge"] if profile is not None else float("-inf")
    confidence = _numeric_hint(candidate.get("confidence"))
    confidence_value = confidence if confidence is not None else float("-inf")
    # Last, as a tiebreaker only -- same placement and same reasoning as
    # build_intelligence_board_contract's card sort: folding
    # source_summary_score into `score` directly was tried there and
    # regressed test_intelligence_query_prioritizes_ready_advanced_inputs
    # (a qualitative text signal outranking a data-readiness one). It only
    # speaks when score/edge/confidence are genuinely tied, which is exactly
    # the case two props on identical line/odds/confidence but opposite
    # recent-form writeups produce.
    source_summary_score = _numeric_hint(candidate.get("source_summary_score")) or 0.0
    return advanced_ready, score, edge, confidence_value, source_summary_score


def _candidate_correlation_score(first_candidate: dict[str, Any], second_candidate: dict[str, Any]) -> float:
    try:
        return float(_compute_candidate_correlation(first_candidate, second_candidate).get("correlation_score") or 0.0)
    except Exception:
        return 0.0


def _greedy_low_correlation_selection(
    candidates: list[dict[str, Any]],
    *,
    limit: int,
    threshold: float = MAX_CORRELATION_THRESHOLD,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=_candidate_betting_rank_key, reverse=True):
        if len(selected) >= limit:
            break
        if any(abs(_candidate_correlation_score(candidate, existing)) > threshold for existing in selected):
            continue
        selected.append(candidate)
    return selected


def _candidate_confidence(candidate: dict[str, Any]) -> float:
    source_confidence = _pct_hint(candidate.get("confidence"))
    relevant_signals = [signal for signal in _relevant_advanced_signals(candidate) if isinstance(signal, dict)]
    signal_count = len(relevant_signals)
    direction_votes: list[int] = []
    for signal in relevant_signals:
        delta = _advanced_signal_delta(signal)
        if delta is None:
            continue
        if delta > 0:
            direction_votes.append(1)
        elif delta < 0:
            direction_votes.append(-1)

    if len(direction_votes) == 1:
        agreement = 0.5
    elif direction_votes:
        agreement = abs(sum(direction_votes)) / float(len(direction_votes))
    else:
        agreement = 0.0

    readiness = candidate.get("advanced_gate") if isinstance(candidate.get("advanced_gate"), dict) else {}
    readiness_ratio = float(readiness.get("ratio") or 0.0)
    missing_inputs = readiness.get("missing_inputs") if isinstance(readiness.get("missing_inputs"), list) else []
    publish_missing_inputs = readiness.get("publish_missing_inputs") if isinstance(readiness.get("publish_missing_inputs"), list) else []
    missing_penalty = min(
        0.35,
        (len(missing_inputs) * 0.08) + (len(publish_missing_inputs) * 0.03) + (max(0.0, 1.0 - readiness_ratio) * 0.15),
    )

    signal_count_factor = min(1.0, float(signal_count) / 6.0)
    confidence = 0.20 + (signal_count_factor * 0.35) + (agreement * 0.30) + (readiness_ratio * 0.20) - missing_penalty
    if source_confidence is not None:
        confidence = max(confidence, float(source_confidence) / 100.0)
    return round(max(0.0, min(1.0, confidence)), 2)


def _simulation_model_probability(candidate: dict[str, Any]) -> float | None:
    simulation = candidate.get("simulation") if isinstance(candidate.get("simulation"), dict) else {}
    if not simulation:
        return None

    def _lookup_normalized(mapping: dict[str, Any], target_key: str | None) -> Any:
        if not isinstance(mapping, dict) or not target_key:
            return None
        normalized_target = _normalized_market_text(target_key)
        if not normalized_target:
            return None
        for actual_key, value in mapping.items():
            if _normalized_market_text(str(actual_key)) == normalized_target:
                return value
        return None

    market_text = _normalized_market_text(_safe_text(candidate.get("market"), _safe_text(candidate.get("market_key"), "")))
    selection_direction = _candidate_selection_direction(candidate)
    line_value = _numeric_hint(candidate.get("line") or candidate.get("market_line") or candidate.get("prop_line"))

    distributions = simulation.get("probability_distributions") if isinstance(simulation.get("probability_distributions"), dict) else simulation.get("distribution")
    if isinstance(distributions, dict) and market_text in _GAME_SIDE_MARKETS:
        win_probability = _numeric_hint(distributions.get("win"))
        if win_probability is not None:
            return max(0.0, min(1.0, win_probability))

    if selection_direction == 0 or line_value is None:
        if isinstance(distributions, dict):
            win_probability = _numeric_hint(distributions.get("win"))
            if win_probability is not None:
                return max(0.0, min(1.0, win_probability))
        return None

    player_name = _candidate_subject_key(candidate)
    stat_name = _candidate_market_key(candidate)
    player_distributions = simulation.get("player_stat_distributions") if isinstance(simulation.get("player_stat_distributions"), dict) else {}
    player_distribution = _lookup_normalized(player_distributions, player_name)
    stat_distribution = _lookup_normalized(player_distribution, stat_name)

    if isinstance(stat_distribution, dict):
        mean_value = _numeric_hint(stat_distribution.get("mean"))
        std_dev_value = _numeric_hint(stat_distribution.get("std_dev"))
        if mean_value is not None and std_dev_value is not None and std_dev_value > 0:
            cdf = NormalDist(mu=mean_value, sigma=std_dev_value).cdf(line_value)
            if selection_direction < 0:
                return max(0.0, min(1.0, cdf))
            if selection_direction > 0:
                return max(0.0, min(1.0, 1.0 - cdf))

    if isinstance(distributions, dict):
        win_probability = _numeric_hint(distributions.get("win"))
        if win_probability is not None:
            return max(0.0, min(1.0, win_probability))
    return None


def _candidate_model_probability(candidate: dict[str, Any]) -> float | None:
    simulation_probability = _simulation_model_probability(candidate)
    if simulation_probability is not None:
        return simulation_probability
    score_value = _numeric_hint(candidate.get("score"))
    if score_value is None:
        return None
    return max(0.0, min(1.0, float(score_value) / 100.0))


def _candidate_rationale(candidate: dict[str, Any]) -> str:
    advanced_context = candidate.get("advanced_context") if isinstance(candidate.get("advanced_context"), list) else []
    advanced_driver_text = _advanced_driver_text(advanced_context)
    advanced_gate = candidate.get("advanced_gate") if isinstance(candidate.get("advanced_gate"), dict) else {}
    market_context = candidate.get("market_context") if isinstance(candidate.get("market_context"), dict) else {}
    market_fit = candidate.get("market_fit") if isinstance(candidate.get("market_fit"), dict) else {}
    source_summary = (
        _safe_text(candidate.get("writeup"), "")
        or _safe_text(candidate.get("detail"), "")
        or _safe_text(candidate.get("summary"), "")
    )
    state_note = _safe_text(candidate.get("state_note"), "")
    if _safe_text(candidate.get("candidate_type"), "") == "game":
        notes: list[str] = []
        if source_summary:
            notes.append(source_summary if source_summary.endswith(".") else f"{source_summary}.")
        if state_note:
            notes.append(state_note if state_note.endswith(".") else f"{state_note}.")
        if _safe_text(candidate.get("projected"), "-") != "-" and _safe_text(candidate.get("line"), "-") != "-":
            notes.append(f"Model projection is {candidate.get('projected')} versus a book line of {candidate.get('line')}.")
        if bool(candidate.get("is_live")) and _safe_text(candidate.get("live_projection"), "-") != "-":
            notes.append(f"Live model projection is {candidate.get('live_projection')} versus a current line of {candidate.get('line')}.")
        if _safe_text(candidate.get("edge"), "-") != "-":
            notes.append(f"Model edge is {candidate.get('edge')} against the current book price.")
        if _safe_text(candidate.get("confidence"), "-") != "-":
            notes.append(f"Win-rate confidence sits at {candidate.get('confidence')}.")
        if _safe_text(candidate.get("odds"), "-") != "-":
            notes.append(f"The quoted book number is {candidate.get('odds')} on {candidate.get('pick')}.")
        if market_context.get("implied_probability") is not None:
            notes.append(f"Market implied probability is {market_context.get('implied_probability')}%.")
        if market_context.get("price_edge_pct") is not None:
            notes.append(f"Model versus price edge is {market_context.get('price_edge_pct')} points.")
        if advanced_driver_text:
            notes.append(f"Advanced drivers in play: {advanced_driver_text}.")
        missing_inputs = advanced_gate.get("missing_inputs") if isinstance(advanced_gate.get("missing_inputs"), list) else []
        if missing_inputs:
            notes.append(f"Readiness is partial because {len(missing_inputs)} advanced inputs are missing or unpublished.")
        return " ".join(notes) or "The game board shows a playable sportsbook edge with support from the current model snapshot."

    notes = []
    if source_summary:
        notes.append(source_summary if source_summary.endswith(".") else f"{source_summary}.")
    if state_note:
        notes.append(state_note if state_note.endswith(".") else f"{state_note}.")
    if _safe_text(candidate.get("projected"), "-") != "-" and _safe_text(candidate.get("line"), "-") != "-":
        notes.append(f"Model projection is {candidate.get('projected')} versus a book line of {candidate.get('line')}.")
    if bool(candidate.get("is_live")) and _safe_text(candidate.get("live_projection"), "-") != "-":
        actual_value = _safe_text(candidate.get("actual"), "-")
        notes.append(f"Live rest-of-game projection is {candidate.get('live_projection')} with current box score at {actual_value}.")
    if _safe_text(candidate.get("edge"), "-") != "-":
        notes.append(f"The stored edge reads {candidate.get('edge')}.")
    if _safe_text(candidate.get("confidence"), "-") != "-":
        notes.append(f"Sim confidence is {candidate.get('confidence')}.")
    if market_context.get("implied_probability") is not None:
        notes.append(f"Market implied probability is {market_context.get('implied_probability')}%.")
    if market_context.get("price_edge_pct") is not None:
        notes.append(f"Model versus price edge is {market_context.get('price_edge_pct')} points.")
    if _safe_text(market_fit.get("market_fit_note"), ""):
        notes.append(f"Market fit: {market_fit.get('market_fit_note')}.")
    if _safe_text(candidate.get("live_total"), "-") != "-":
        notes.append(f"Game context currently points to a live total of {candidate.get('live_total')}.")
    if advanced_driver_text:
        notes.append(f"Advanced drivers in play: {advanced_driver_text}.")
    signal_text = _advanced_signal_text(candidate)
    if signal_text:
        notes.append(f"Candidate-level advanced signals: {signal_text}.")
    statcast_text = _mlb_statcast_profile_text(candidate.get("mlb_statcast_profile") if isinstance(candidate.get("mlb_statcast_profile"), dict) else None)
    if statcast_text:
        notes.append(f"Raw Statcast context: {statcast_text}.")
    missing_inputs = advanced_gate.get("missing_inputs") if isinstance(advanced_gate.get("missing_inputs"), list) else []
    if missing_inputs:
        notes.append(f"Readiness is partial because {len(missing_inputs)} advanced inputs are missing or unpublished.")
    return " ".join(notes) or "The prop sits above the local model threshold with enough context to justify a sportsbook-facing recommendation."


def _candidate_live_actual_value(candidate: dict[str, Any]) -> float | None:
    if _safe_text(candidate.get("sport_slug"), "").lower() != "mlb":
        return None
    game_pk = _safe_int(candidate.get("game_pk"))
    context_label = _safe_text(candidate.get("context_label"), "")
    if game_pk is None or not context_label:
        return None
    try:
        from syndicate.blueprints.home import _mlb_actual_payload_for_candidate
        from syndicate.blueprints.home import _mlb_prop_actual_value
    except Exception:
        return None
    try:
        actual_payload = _mlb_actual_payload_for_candidate(context_label, int(game_pk), {})
    except Exception:
        actual_payload = None
    if not isinstance(actual_payload, dict):
        return None
    try:
        return _mlb_prop_actual_value(candidate, actual_payload)
    except Exception:
        return None


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    market_context = candidate.get("market_context") if isinstance(candidate.get("market_context"), dict) else {}
    market_fit = candidate.get("market_fit") if isinstance(candidate.get("market_fit"), dict) else {}
    market_key = _candidate_market_key(candidate)
    drivers = [dict(item) for item in (candidate.get("signal_contributions_top_positive") or []) if isinstance(item, dict)][:3]
    risks = [dict(item) for item in (candidate.get("signal_contributions_top_negative") or []) if isinstance(item, dict)][:2]
    output = {
        "candidate_type": _safe_text(candidate.get("candidate_type"), "candidate"),
        "sport": _safe_text(candidate.get("sport"), "Sport"),
        "sport_slug": _safe_text(candidate.get("sport_slug"), "sport"),
        "matchup": _safe_text(candidate.get("matchup"), "-"),
        "team": _safe_text(candidate.get("team"), candidate.get("player_team"), "—"),
        "player_name": _safe_text(candidate.get("player_name"), candidate.get("name"), "—"),
        "market": _safe_text(candidate.get("market"), "Market"),
        "market_key": market_fit.get("market_key") or market_key,
        "market_label": market_fit.get("market_label"),
        "market_shape": market_fit.get("market_shape"),
        "market_fit_score": market_fit.get("market_fit_score"),
        "market_fit_note": market_fit.get("market_fit_note"),
        "pick": _safe_text(candidate.get("pick"), _safe_text(candidate.get("name"), "Play")),
        "name": _safe_text(candidate.get("name"), _safe_text(candidate.get("pick"), "Play")),
        "surface": _safe_text(candidate.get("surface_title"), _safe_text(candidate.get("surface"), "Board")),
        "is_live": bool(candidate.get("is_live")),
        "is_final": bool(candidate.get("is_final")),
        "line": _safe_text(candidate.get("line"), "-"),
        "odds": _safe_text(candidate.get("odds"), "-"),
        "american_odds": market_context.get("american_odds"),
        "decimal_odds": market_context.get("decimal_odds"),
        "implied_probability": market_context.get("implied_probability"),
        "model_probability": market_context.get("model_probability"),
        "price_edge_pct": market_context.get("price_edge_pct"),
        "edge": _safe_text(candidate.get("edge"), "-"),
        "expected_value": candidate.get("expected_value"),
        "volatility": candidate.get("volatility"),
        "volatility_score": candidate.get("volatility_score"),
        "adjusted_edge": candidate.get("adjusted_edge"),
        "confidence": _safe_text(candidate.get("confidence"), "-"),
        "projected": _safe_text(candidate.get("projected"), "-"),
        "live_projection": _safe_text(candidate.get("live_projection"), "-"),
        "sim_projection": _safe_text(candidate.get("sim_projection"), candidate.get("projected"), "-"),
        "movement": candidate.get("movement") if isinstance(candidate.get("movement"), dict) else None,
        "delta": candidate.get("delta"),
        "percent_change": candidate.get("percent_change"),
        "recent_movement_trend": _safe_text(candidate.get("recent_movement_trend") or (candidate.get("movement") or {}).get("trend"), "flat"),
        "last_updated": candidate.get("last_updated") or (candidate.get("movement") or {}).get("last_updated"),
        "actual": _safe_text(candidate.get("actual"), "-"),
        "status_display": _safe_text(candidate.get("status_display"), "-"),
        "status_context": _safe_text(candidate.get("status_context"), "-"),
        "game_pk": candidate.get("game_pk"),
        "game_id": _safe_text(candidate.get("game_id"), ""),
        "event_id": _safe_text(candidate.get("event_id"), ""),
        "player_team": _safe_text(candidate.get("player_team"), candidate.get("team"), "—"),
        "state_note": _safe_text(candidate.get("state_note"), ""),
        "settlement": _candidate_settlement_summary(candidate),
        "href": candidate.get("href"),
        "href_label": _safe_text(candidate.get("href_label"), "Open board"),
        "rationale": _candidate_rationale(candidate),
        "score": round(float(candidate.get("score") or 0.0), 2),
        "advanced_ready": bool((candidate.get("advanced_gate") or {}).get("ready")),
        "advanced_readiness": _readiness_label(candidate.get("advanced_gate") or {}),
        "missing_advanced_inputs": [
            {
                "label": _safe_text(item.get("label"), "Advanced input"),
                "path": _safe_text(item.get("path"), "-"),
                "missing_reason": _safe_text(item.get("missing_reason"), "missing"),
            }
            for item in ((candidate.get("advanced_gate") or {}).get("missing_inputs") or [])[:3]
            if isinstance(item, dict)
        ],
        "advanced_inputs": [
            {
                "label": _safe_text(item.get("label"), "Advanced input"),
                "metrics": [str(metric).strip() for metric in (item.get("metrics") or []) if str(metric).strip()][:5],
            }
            for item in (candidate.get("advanced_context") or [])[:2]
            if isinstance(item, dict)
        ],
        "advanced_signals": [
            {
                "key": _safe_text(item.get("key"), "signal"),
                "label": _safe_text(item.get("label"), "Advanced signal"),
                "value": item.get("value"),
            }
            for item in (candidate.get("advanced_signals") or [])[:6]
            if isinstance(item, dict)
        ],
        "drivers": drivers,
        "risks": risks,
        "market_context": {
            "odds": candidate.get("odds"),
            "implied_probability": market_context.get("implied_probability"),
            "edge": candidate.get("edge"),
            "adjusted_edge": candidate.get("adjusted_edge"),
        },
        "advanced_signal_score": round(float(candidate.get("advanced_signal_score") or 0.0), 2),
        "source_summary_score": round(float(candidate.get("source_summary_score") or 0.0), 2),
        "selection_direction": _candidate_selection_direction(candidate),
        "subject_key": _candidate_subject_key(candidate),
        "team_key": _candidate_team_key(candidate),
        "mlb_statcast_profile": candidate.get("mlb_statcast_profile") if isinstance(candidate.get("mlb_statcast_profile"), dict) else None,
    }
    pills = candidate.get("display_pills") if isinstance(candidate.get("display_pills"), list) else []
    output["display_pills"] = [str(item).strip() for item in pills if str(item).strip()][:6]
    return output


def _candidate_settlement_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    status_text = _safe_text(
        candidate.get("status_display")
        or candidate.get("status_context")
        or candidate.get("game_state")
        or "",
        "",
    ).lower()
    actual_value = _safe_text(
        candidate.get("actual")
        or candidate.get("actual_value")
        or candidate.get("actual_so_far")
        or candidate.get("current_actual")
        or candidate.get("live_actual"),
        "-",
    )
    if actual_value in {"", "-"}:
        live_actual_value = _candidate_live_actual_value(candidate)
        if live_actual_value is not None:
            actual_value = _safe_text(live_actual_value, "-")
    line_value = _numeric_hint(candidate.get("line"))
    actual_numeric = _numeric_hint(actual_value)
    is_final = bool(candidate.get("is_final")) or any(token in status_text for token in ("final", "completed", "settled", "graded"))
    is_live = bool(candidate.get("is_live"))

    if is_final:
        status = "settled"
    elif is_live:
        status = "live"
    elif actual_value not in {"", "-"}:
        status = "resolved"
    else:
        status = "pending"

    result = _safe_text(candidate.get("settlement_result") or candidate.get("result"), "")
    if not result and status == "settled" and actual_numeric is not None and line_value is not None:
        selection_text = _safe_text(candidate.get("selection") or candidate.get("pick"), "").lower()
        over_selected = selection_text.startswith("over") or " over " in selection_text
        under_selected = selection_text.startswith("under") or " under " in selection_text
        if actual_numeric == line_value:
            result = "push"
        elif over_selected:
            result = "won" if actual_numeric > line_value else "lost"
        elif under_selected:
            result = "won" if actual_numeric < line_value else "lost"

    status_label = {
        "live": "Live",
        "resolved": "Resolved",
        "settled": "Settled",
        "pending": "Pending",
    }.get(status, status.title() if status else "")

    return {
        "status": status,
        "status_label": status_label,
        "actual": actual_value,
        "line": _safe_text(candidate.get("line"), "-"),
        "result": result,
        "is_live": is_live,
        "is_final": is_final,
    }




def build_edge_board_view(response: dict[str, Any], *, top_limit: int | None = None) -> dict[str, Any]:
    picks = response.get("picks") if isinstance(response.get("picks"), list) else []
    portfolio = response.get("portfolio") if isinstance(response.get("portfolio"), dict) else {}
    parlays = response.get("parlays") if isinstance(response.get("parlays"), list) else []

    def _edge_value(pick: dict[str, Any]) -> float:
        edge_value = pick.get("edge")
        if edge_value is None:
            return float("-inf")
        try:
            return float(edge_value)
        except (TypeError, ValueError):
            return float("-inf")

    sorted_picks = sorted((pick for pick in picks if isinstance(pick, dict)), key=_edge_value, reverse=True)
    top_picks = list(sorted_picks)

    picks_by_sport: dict[str, list[dict[str, Any]]] = {}
    picks_by_game: dict[str, list[dict[str, Any]]] = {}
    for pick in sorted_picks:
        sport_key = _safe_text(pick.get("sport"), "Sport")
        picks_by_sport.setdefault(sport_key, []).append(pick)

        correlation_group = pick.get("correlation_group") if isinstance(pick.get("correlation_group"), dict) else {}
        game_key = _safe_text(correlation_group.get("key") or correlation_group.get("label"), "candidate")
        picks_by_game.setdefault(game_key, []).append(pick)

    return {
        "top_picks": top_picks,
        "portfolio_summary": portfolio,
        "parlay_opportunities": [dict(parlay) for parlay in parlays if isinstance(parlay, dict)],
        "grouped_picks_by_sport": picks_by_sport,
        "grouped_picks_by_game": picks_by_game,
    }


def build_portfolio_panel_view(portfolio: dict[str, Any]) -> dict[str, Any]:
    risk_profile = portfolio.get("risk_profile") if isinstance(portfolio.get("risk_profile"), dict) else {}

    def _number(*values: Any, default: float = 0.0) -> float:
        for value in values:
            try:
                if value is None:
                    continue
                return float(value)
            except (TypeError, ValueError):
                continue
        return default

    exposure_value = _number(portfolio.get("total_exposure"))
    expected_return_value = _number(portfolio.get("expected_return"))
    risk_level = _safe_text(risk_profile.get("level") or portfolio.get("risk_level"), "low")
    diversification_score = _number(risk_profile.get("diversification_score"), portfolio.get("diversification_score"))
    average_correlation = _number(risk_profile.get("average_correlation"), portfolio.get("average_correlation"))

    health_flags: list[str] = []
    if diversification_score > 0.8:
        health_flags.append("well_diversified")
    if average_correlation < 0.15:
        health_flags.append("low_correlation")

    return {
        "exposure": f"{exposure_value * 100.0:.1f}%",
        "expected_return": f"{expected_return_value * 100.0:+.2f}%",
        "risk_level": risk_level[:1].upper() + risk_level[1:].lower() if risk_level else "Low",
        "diversification_score": f"{diversification_score:.2f}",
        "correlation_display": f"{average_correlation:.2f}",
        "health_flags": health_flags,
    }


def build_parlay_card_view(parlay: dict[str, Any]) -> dict[str, Any]:
    correlation_score = _numeric_hint(parlay.get("correlation_score"))
    if correlation_score is None:
        correlation_score = _numeric_hint((parlay.get("correlation_profile") or {}).get("max_correlation"))
    correlation_label = "High"
    if correlation_score is not None and correlation_score < 0.3:
        correlation_label = "Low"
    elif correlation_score is not None and correlation_score < 0.5:
        correlation_label = "Moderate"

    probability_value = _numeric_hint(parlay.get("combined_probability"))
    edge_value = _numeric_hint(parlay.get("combined_edge"))
    expected_value = _numeric_hint(parlay.get("expected_value") if parlay.get("expected_value") is not None else parlay.get("combined_expected_value"))

    return {
        "legs": [dict(leg) for leg in (parlay.get("legs") or []) if isinstance(leg, dict)],
        "probability_display": f"{probability_value * 100.0:.1f}%" if probability_value is not None else "-",
        "edge_display": f"{edge_value * 100.0:+.1f}%" if edge_value is not None else "-",
        "ev_display": f"{expected_value * 100.0:+.2f}%" if expected_value is not None else "-",
        "correlation_label": correlation_label,
    }


def build_pick_card_view(pick: dict[str, Any]) -> dict[str, Any]:
    visual = pick.get("visual") if isinstance(pick.get("visual"), dict) else {}
    movement = pick.get("movement") if isinstance(pick.get("movement"), dict) else {}
    probabilities = pick.get("probabilities") if isinstance(pick.get("probabilities"), dict) else {}
    delta_value = movement.get("delta")
    delta_display = movement.get("delta_display") or movement.get("edge_delta")
    if delta_display is None and delta_value is not None:
        delta_display = f"{float(delta_value):+g}"
    percent_change_value = movement.get("percent_change")
    percent_change_display = movement.get("percent_change_display")
    if percent_change_display is None and percent_change_value is not None:
        percent_change_display = f"{float(percent_change_value):.2f}%"
    return {
        "title": _safe_text(pick.get("selection") or pick.get("pick") or pick.get("name"), "Play"),
        "edge_display": pick.get("edge_display") or pick.get("edge"),
        "confidence_display": pick.get("confidence_display") or pick.get("confidence"),
        "probability_display": {
            "model": pick.get("model_probability_display") or probabilities.get("model_probability") or pick.get("model_probability"),
            "market": pick.get("implied_probability_display") or probabilities.get("implied_probability") or pick.get("implied_probability"),
        },
        "bet_size_display": pick.get("bet_size_display") or pick.get("recommended_bet_size") or pick.get("bet_size"),
        "risk_label": _safe_text(pick.get("risk_label") or pick.get("risk_level"), ""),
        "drivers": pick.get("drivers") if isinstance(pick.get("drivers"), list) else [],
        "risks": pick.get("risks") if isinstance(pick.get("risks"), list) else [],
        "badges": [
            visual.get("edge_tier"),
            visual.get("confidence_tier"),
            visual.get("risk_tier"),
        ],
        "movement": {
            "trend": _safe_text(movement.get("trend") or pick.get("recent_movement_trend"), "flat"),
            "delta_display": delta_display,
            "percent_change_display": percent_change_display,
            "last_updated": movement.get("last_updated") or pick.get("last_updated"),
        },
    }


def _supporting_evidence_table(analysis_views: dict[str, Any]) -> dict[str, Any] | None:
    table = analysis_views.get("table") if isinstance(analysis_views.get("table"), dict) else {}
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    if not rows:
        return None
    evidence_rows: list[dict[str, Any]] = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        evidence_rows.append(
            {
                "target": _safe_text(row.get("label") or row.get("player") or row.get("name"), "Target"),
                "matchup": _safe_text(row.get("matchup"), "-"),
                "market": _safe_text(row.get("market"), "Market"),
                "pick": _safe_text(row.get("pick"), "-"),
                "score": row.get("score"),
                "why": _safe_text(row.get("why"), "-"),
            }
        )
    if not evidence_rows:
        return None
    return {
        "kind": "table",
        "title": _safe_text(table.get("title"), "Evidence grid"),
        "columns": ["target", "matchup", "market", "pick", "score", "why"],
        "rows": evidence_rows,
    }


def _recent_form_supporting_evidence_table(analysis_views: dict[str, Any]) -> dict[str, Any] | None:
    focus = _safe_text(analysis_views.get("focus"), "").lower()
    if focus not in {"nba_matchups", "wnba_matchups", "ncaab_matchups"}:
        return None
    table = analysis_views.get("table") if isinstance(analysis_views.get("table"), dict) else {}
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    if not rows:
        return None
    recent_form_rows: list[dict[str, Any]] = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        if all(
            row.get(key) in {None, ""}
            for key in [
                "last5_average",
                "last10_average",
                "last_game_value",
                "projected_minutes",
                "last10_workload",
                "last5_delta_signal",
                "last10_delta_signal",
                "last_game_delta_signal",
                "workload_delta_signal",
            ]
        ):
            continue
        recent_form_rows.append(
            {
                "target": _safe_text(row.get("label") or row.get("player") or row.get("name"), "Target"),
                "market": _safe_text(row.get("market"), "Market"),
                "last5_average": row.get("last5_average"),
                "last10_average": row.get("last10_average"),
                "last_game_value": row.get("last_game_value"),
                "projected_minutes": row.get("projected_minutes"),
                "last10_workload": row.get("last10_workload"),
                "last5_delta_signal": row.get("last5_delta_signal"),
                "last10_delta_signal": row.get("last10_delta_signal"),
                "last_game_delta_signal": row.get("last_game_delta_signal"),
                "workload_delta_signal": row.get("workload_delta_signal"),
                "why": _safe_text(row.get("why"), "-"),
            }
        )
    if not recent_form_rows:
        return None
    return {
        "kind": "table",
        "title": "Recent form table",
        "columns": ["target", "market", "last5_average", "last10_average", "last_game_value", "projected_minutes", "last10_workload", "last5_delta_signal", "last10_delta_signal", "last_game_delta_signal", "workload_delta_signal", "why"],
        "rows": recent_form_rows,
    }


def _build_supporting_evidence(
    recommendations: list[dict[str, Any]],
    analysis_views: dict[str, Any] | None,
    *,
    display_limit: int | None = None,
) -> dict[str, Any] | None:
    if not recommendations:
        return None

    top = recommendations[0] if isinstance(recommendations[0], dict) else {}
    sections: list[dict[str, Any]] = []

    metric_items = [
        {"label": "Projection", "value": top.get("projected")},
        {"label": "Line", "value": top.get("line")},
        {"label": "Live projection", "value": top.get("live_projection")},
        {"label": "Confidence", "value": _format_probability_display(top.get("confidence"))},
        {"label": "Price edge", "value": f"{top.get('price_edge_pct')}%" if top.get("price_edge_pct") is not None else None},
        {"label": "Implied probability", "value": _format_probability_display(top.get("implied_probability"))},
        {"label": "Market fit", "value": top.get("market_fit_score")},
        {"label": "Advanced signal score", "value": top.get("advanced_signal_score")},
        {"label": "Source summary score", "value": top.get("source_summary_score")},
    ]
    metric_items = [item for item in metric_items if item.get("value") not in {None, "", "-"}]
    if metric_items:
        sections.append({"kind": "metrics", "title": "Top case evidence", "items": metric_items})

    signal_items = [
        {"label": _safe_text(item.get("label"), "Advanced signal"), "value": item.get("value")}
        for item in (top.get("advanced_signals") or [])[:6]
        if isinstance(item, dict) and item.get("value") not in {None, ""}
    ]
    if not signal_items and isinstance(analysis_views, dict):
        chart = analysis_views.get("chart") if isinstance(analysis_views.get("chart"), dict) else {}
        chart_rows = chart.get("rows") if isinstance(chart.get("rows"), list) else []
        chart_series = chart.get("series") if isinstance(chart.get("series"), list) else []
        first_chart_row = chart_rows[0] if chart_rows and isinstance(chart_rows[0], dict) else {}
        signal_items = [
            {"label": _humanize_signal_key(key), "value": first_chart_row.get(key)}
            for key in chart_series[:6]
            if key not in {"score", "market_fit_score", "advanced_signal_score", "source_summary_score"} and first_chart_row.get(key) not in {None, ""}
        ]
    if signal_items:
        sections.append({"kind": "signals", "title": "Key advanced signals", "items": signal_items})

    source_items: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for recommendation in recommendations:
        if not isinstance(recommendation, dict):
            continue
        for item in (recommendation.get("advanced_inputs") or [])[:3]:
            if not isinstance(item, dict):
                continue
            label = _safe_text(item.get("label"), "Advanced input")
            if label in seen_sources:
                continue
            seen_sources.add(label)
            metrics = [str(metric).strip() for metric in (item.get("metrics") or []) if str(metric).strip()]
            source_items.append({"label": label, "detail": ", ".join(metrics[:5]) if metrics else None})
    if source_items:
        sections.append({"kind": "sources", "title": "Source inputs", "items": source_items})

    if isinstance(analysis_views, dict):
        recent_form_table = _recent_form_supporting_evidence_table(analysis_views)
        if recent_form_table is not None:
            sections.append(recent_form_table)
        evidence_table = _supporting_evidence_table(analysis_views)
        if evidence_table is not None:
            sections.append(evidence_table)

    if not sections:
        return None

    return {
        "title": "Supporting evidence",
        "focus": analysis_views.get("focus") if isinstance(analysis_views, dict) else None,
        "sections": sections,
    }


def _build_analysis_brief(
    recommendations: list[dict[str, Any]],
    analysis_views: dict[str, Any] | None,
    supporting_evidence: dict[str, Any] | None,
    *,
    preferences: dict[str, Any],
) -> dict[str, Any] | None:
    return _runtime_build_analysis_brief(
        recommendations,
        analysis_views,
        supporting_evidence,
        preferences=preferences,
        safe_text=_safe_text,
        humanize_signal_key=_humanize_signal_key,
    )


def _confidence_value_from_candidate(candidate: dict[str, Any], *, sport: str | None = None) -> float:
    confidence_pct = _pct_hint(candidate.get("confidence"))
    if confidence_pct is not None:
        base_confidence = round(min(0.99, max(0.01, float(confidence_pct) / 100.0)), 2)
    else:
        score_value = _numeric_hint(candidate.get("score"))
        if score_value is not None:
            base_confidence = round(min(0.99, max(0.01, float(score_value) / 100.0)), 2)
        else:
            market_fit_score = _numeric_hint(candidate.get("market_fit_score"))
            if market_fit_score is not None:
                base_confidence = round(min(0.99, max(0.01, 0.35 + (float(market_fit_score) / 200.0))), 2)
            else:
                base_confidence = 0.5
    return base_confidence


def _manifest_supporting_data(selected_date: str, overview: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sport_slugs = [
        _safe_text(row.get("slug"), "sport").lower()
        for row in overview
        if isinstance(row, dict)
    ]
    manifests = load_artifact_manifests(selected_date=selected_date, sport_slugs=sport_slugs)
    supporting: list[dict[str, Any]] = []
    for manifest in manifests:
        payload = manifest.to_dict() if hasattr(manifest, "to_dict") else dict(manifest)
        counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
        if not any(int(counts.get(key) or 0) for key in ("predictions", "edges", "recommendations", "live_data")):
            continue
        primary_paths: list[str] = []
        for category in ("predictions", "edges", "recommendations", "live_data"):
            refs = payload.get(category) if isinstance(payload.get(category), list) else []
            for ref in refs[:1]:
                if not isinstance(ref, dict):
                    continue
                path_value = _safe_text(ref.get("relative_path") or ref.get("path"), "")
                if path_value:
                    primary_paths.append(path_value)
                    break
        supporting.append(
            {
                "kind": "artifact_manifest",
                "sport": payload.get("sport_slug"),
                "selected_date": payload.get("selected_date"),
                "counts": {
                    "predictions": int(counts.get("predictions") or 0),
                    "edges": int(counts.get("edges") or 0),
                    "recommendations": int(counts.get("recommendations") or 0),
                    "live_data": int(counts.get("live_data") or 0),
                },
                "paths": primary_paths[:4],
            }
        )
        if len(supporting) >= 3:
            break
    return supporting


def _reliability_supporting_data(
    top: dict[str, Any],
    overview: list[dict[str, Any]],
    selected_date: str,
    confidence: float,
    profile: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str | None]:
    sport_slug = _safe_text(top.get("sport_slug"), "") or (_safe_text(overview[0].get("slug"), "") if overview else "")
    profile = profile or build_reliability_profile(sport=sport_slug or None)
    sample_size = int(profile.get("sample_size") or 0)
    if sample_size <= 0:
        return {}, None
    calibration_error = float(profile.get("calibration_error") or 0.0)
    note = f"Historical calibration MAE for {sport_slug or 'this board'} is {calibration_error:.2f}, so the confidence score is reliability-adjusted."
    return {
        "kind": "model_reliability",
        "sport": sport_slug or None,
        "selected_date": selected_date,
        "sample_size": sample_size,
        "win_rate": profile.get("metrics", {}).get("win_rate"),
        "roi": profile.get("metrics", {}).get("roi"),
        "clv": profile.get("metrics", {}).get("clv"),
        "calibration_error": calibration_error,
        "calibration_penalty": profile.get("calibration_penalty"),
        "reliability_multiplier": profile.get("reliability_multiplier"),
        "confidence_after_reliability": confidence,
    }, note


def _build_structured_answer(
    result: dict[str, Any],
    recommendations: list[dict[str, Any]],
    analysis_views: dict[str, Any] | None,
    supporting_evidence: dict[str, Any] | None,
    board_notes: list[str],
    readiness_gate: dict[str, Any],
    overview: list[dict[str, Any]],
) -> dict[str, Any]:
    top = recommendations[0] if recommendations else {}
    summary = (
        _safe_text(top.get("summary"), "")
        or _safe_text(top.get("rationale"), "")
        or _safe_text(result.get("summary"), "")
        or _safe_text(result.get("headline"), "")
        or "No clear answer surfaced from the current local board."
    )
    if top.get("name") and top.get("name") not in summary:
        summary = f"{_safe_text(top.get('name'), 'Top candidate')}: {summary}"

    key_factors: list[str] = []
    for value in (
        _safe_text(top.get("market_fit_note"), ""),
        _safe_text(top.get("summary"), ""),
        _safe_text(top.get("rationale"), ""),
        _safe_text(top.get("writeup"), ""),
    ):
        if value and value not in key_factors:
            key_factors.append(value)
    if isinstance(analysis_views, dict):
        focus = _safe_text(analysis_views.get("focus"), "")
        if focus:
            key_factors.append(f"Analysis focus: {focus}.")
    if isinstance(supporting_evidence, dict):
        evidence_titles = [
            _safe_text(section.get("title"), "")
            for section in (supporting_evidence.get("sections") or [])
            if isinstance(section, dict)
        ]
        evidence_titles = [item for item in evidence_titles if item]
        if evidence_titles:
            key_factors.append(f"Evidence sections: {', '.join(evidence_titles[:3])}.")

    if not key_factors:
        key_factors.append("The answer is being driven by the top local candidate and the evidence returned for the current board.")

    risks = [note for note in board_notes if note]
    if readiness_gate and not bool(readiness_gate.get("ok", True)):
        status_text = _safe_text(readiness_gate.get("status"), "not ready") or "not ready"
        risks.append(f"Readiness gate status: {status_text}.")
    if result.get("local_only"):
        risks.append("This answer was generated from local-only intelligence artifacts.")
    if not risks:
        risks.append("No explicit board warnings were returned, so the main risk is normal model and market variance.")

    sport_slug = _safe_text(top.get("sport_slug"), "") or (_safe_text(overview[0].get("slug"), "") if overview else "")
    confidence = _confidence_value_from_candidate(top, sport=sport_slug or None)
    if bool(readiness_gate.get("ready")):
        confidence = round(min(0.99, confidence + 0.04), 2)
    else:
        confidence = round(max(0.05, confidence - 0.04), 2)
    confidence, reliability_profile = adjust_confidence(confidence, sport=sport_slug or None)

    recommended_bet_size = None
    risk_level = None
    if top:
        bet_size_profile = _compute_bet_size(top)
        recommended_bet_size = bet_size_profile.get("recommended_bet_size")
        edge_value = _numeric_hint(top.get("adjusted_edge") or top.get("edge")) or 0.0
        volatility_value = _numeric_hint(top.get("volatility_score") or top.get("volatility")) or 0.0
        if volatility_value > 1.0:
            volatility_value = volatility_value / (volatility_value + 1.0)
        confidence_value = max(0.0, min(1.0, confidence))
        risk_score = (max(0.0, 1.0 - confidence_value) * 0.45) + (max(0.0, min(1.0, volatility_value)) * 0.35)
        if edge_value >= 0.0:
            risk_score -= min(0.15, edge_value * 0.10)
        else:
            risk_score += min(0.15, abs(edge_value) * 0.15)
        risk_score = max(0.0, min(1.0, risk_score))
        if risk_score < 0.34:
            risk_level = "low"
        elif risk_score < 0.67:
            risk_level = "medium"
        else:
            risk_level = "high"

    supporting_data: list[dict[str, Any]] = []
    if top:
        supporting_data.append(
            {
                "kind": "top_candidate",
                "name": top.get("name"),
                "market": top.get("market"),
                "matchup": top.get("matchup"),
                "confidence": top.get("confidence"),
                "score": top.get("score"),
                "why": top.get("rationale") or top.get("summary") or top.get("writeup"),
            }
        )
    reliability_data, reliability_note = _reliability_supporting_data(
        top,
        overview,
        _safe_text(result.get("selected_date"), "") or _effective_date(None),
        confidence,
        reliability_profile,
    )
    if reliability_data:
        supporting_data.append(reliability_data)
    if reliability_note:
        risks.append(reliability_note)
    supporting_data.extend(_manifest_supporting_data(_safe_text(result.get("selected_date"), "") or _effective_date(None), overview))
    if isinstance(supporting_evidence, dict):
        supporting_data.append(
            {
                "kind": "supporting_evidence",
                "title": supporting_evidence.get("title"),
                "focus": supporting_evidence.get("focus"),
                "section_count": len(supporting_evidence.get("sections") or []),
            }
        )

    output = {
        "summary": summary,
        "key_factors": key_factors[:5],
        "risks": risks[:5],
        "confidence": confidence,
        "recommended_bet_size": recommended_bet_size,
        "risk_level": risk_level,
        "supporting_data": supporting_data[:6],
        "recommendations": recommendations[:5],
    }
    output["clear_summary"] = summary
    output["deep_analysis"] = key_factors[:3]
    output["risks_uncertainty"] = risks[:5]
    output["recommended_interpretation"] = summary
    output["final_takeaway"] = summary
    return output


def _parlay_rationale(legs: list[dict[str, Any]]) -> str:
    live_count = sum(1 for leg in legs if bool(leg.get("is_live")))
    sports = sorted({_safe_text(leg.get("sport"), "Sport") for leg in legs})
    if live_count and live_count == len(legs):
        return "All legs are coming from live board prices, so the angle is to exploit book lag while the local model is already repricing the same states."
    if live_count:
        return "This mix pairs live board momentum with pregame value so you are not stacking the same timing risk on every leg."
    if len(sports) > 1:
        return "This parlay spreads risk across sports and board types instead of doubling down on one matchup or one feed."
    return "This parlay keeps the legs inside the highest-scoring local recommendations while avoiding duplicate market exposure."


def _parlay_identity(leg: dict[str, Any]) -> str:
    return f"{_safe_text(leg.get('sport_slug'), 'sport')}::{_safe_text(leg.get('pick'), 'pick')}::{_safe_text(leg.get('market'), 'market')}::{_safe_text(leg.get('matchup'), 'matchup')}"


def _parlay_leg_market_shape(leg: dict[str, Any]) -> str:
    return _runtime_parlay_leg_market_shape(
        leg,
        safe_text=_safe_text,
        market_shape_profile=_market_shape_profile,
        market_key_from_text=_market_key_from_text,
    )


def _parlay_leg_market_key(leg: dict[str, Any]) -> str:
    return _runtime_parlay_leg_market_key(
        leg,
        safe_text=_safe_text,
        market_key_from_text=_market_key_from_text,
    )


def _medium_correlation_pair_blocked(sport_slug: str, first_market_key: str, second_market_key: str) -> bool:
    normalized_sport = _safe_text(sport_slug, "").lower()
    normalized_pair = tuple(sorted((_safe_text(first_market_key, "general_market").lower(), _safe_text(second_market_key, "general_market").lower())))
    return (normalized_sport, normalized_pair) in _MEDIUM_CORRELATION_SPORT_MARKET_PAIR_BLOCKS


def _parlay_market_pair_penalty(sport_slug: str, first_market_key: str, second_market_key: str) -> float:
    normalized_sport = _safe_text(sport_slug, "").lower()
    normalized_pair = tuple(sorted((_safe_text(first_market_key, "general_market").lower(), _safe_text(second_market_key, "general_market").lower())))
    return float(_PARLAY_SPORT_MARKET_PAIR_PENALTIES.get((normalized_sport, normalized_pair), 0.0))


def _market_script_cluster(market_key: str) -> str | None:
    return _MARKET_SCRIPT_CLUSTERS.get(_safe_text(market_key, "general_market").lower())


def _parlay_script_cluster_pair_penalty(sport_slug: str, first_market_key: str, second_market_key: str) -> tuple[float, str | None]:
    normalized_sport = _safe_text(sport_slug, "").lower()
    first_cluster = _market_script_cluster(first_market_key)
    second_cluster = _market_script_cluster(second_market_key)
    if not first_cluster or not second_cluster:
        return 0.0, None
    cluster_pair = tuple(sorted((first_cluster, second_cluster)))
    penalty = _SCRIPT_CLUSTER_PAIR_FALLBACK_PENALTIES.get((normalized_sport, cluster_pair))
    if penalty is None:
        return 0.0, None
    cluster_label = first_cluster if first_cluster == second_cluster else f"{first_cluster}/{second_cluster}"
    return float(penalty), f"shared {cluster_label} script"


def _parlay_script_cluster_penalty_multiplier(first_leg: dict[str, Any], second_leg: dict[str, Any]) -> tuple[float, str | None]:
    first_team = _candidate_team_key(first_leg)
    second_team = _candidate_team_key(second_leg)
    first_subject = _candidate_subject_key(first_leg)
    second_subject = _candidate_subject_key(second_leg)
    if not (first_team and second_team and first_subject and second_subject and first_subject != second_subject):
        return 1.0, None
    sport_slug = _safe_text(first_leg.get("sport_slug"), "sport").lower()
    first_cluster = _market_script_cluster(_parlay_leg_market_key(first_leg))
    second_cluster = _market_script_cluster(_parlay_leg_market_key(second_leg))
    if not first_cluster or not second_cluster:
        return 1.0, None
    cluster_pair = tuple(sorted((first_cluster, second_cluster)))
    multiplier = _EXPLICIT_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS.get((sport_slug, cluster_pair))
    if multiplier is None:
        return 1.0, None
    cluster_label = first_cluster if first_cluster == second_cluster else f"{first_cluster}/{second_cluster}"
    return float(multiplier), f"shared {cluster_label} script"


def _parlay_leg_is_live(leg: dict[str, Any]) -> bool:
    if leg.get("is_live") is True:
        return True
    surface_title = _safe_text(leg.get("surface_title"), "").lower()
    return "live" in surface_title


def _parlay_pair_penalty_multiplier(first_leg: dict[str, Any], second_leg: dict[str, Any]) -> tuple[float, str | None]:
    first_live = _parlay_leg_is_live(first_leg)
    second_live = _parlay_leg_is_live(second_leg)
    if first_live and second_live:
        return _LIVE_PARLAY_PAIR_PENALTY_MULTIPLIER, "live"
    if first_live or second_live:
        return _MIXED_TIMING_PARLAY_PAIR_PENALTY_MULTIPLIER, "mixed timing"
    return 1.0, None


def _parlay_pair_direction_multiplier(first_leg: dict[str, Any], second_leg: dict[str, Any]) -> tuple[float, str | None]:
    first_direction = _candidate_selection_direction(first_leg)
    second_direction = _candidate_selection_direction(second_leg)
    if first_direction != 0 and second_direction != 0 and first_direction != second_direction:
        sport_slug = _safe_text(first_leg.get("sport_slug"), "sport").lower()
        first_cluster = _market_script_cluster(_parlay_leg_market_key(first_leg))
        second_cluster = _market_script_cluster(_parlay_leg_market_key(second_leg))
        if first_cluster and second_cluster:
            cluster_pair = tuple(sorted((first_cluster, second_cluster)))
            override = _SCRIPT_CLUSTER_OPPOSING_DIRECTION_MULTIPLIERS.get((sport_slug, cluster_pair))
            if override is not None:
                return float(override), "opposing directions"
        return _OPPOSING_DIRECTION_PARLAY_PAIR_PENALTY_MULTIPLIER, "opposing directions"
    return 1.0, None


def _parlay_pair_subject_multiplier(first_leg: dict[str, Any], second_leg: dict[str, Any]) -> tuple[float, str | None]:
    first_subject = _candidate_subject_key(first_leg)
    second_subject = _candidate_subject_key(second_leg)
    if first_subject and second_subject and first_subject != second_subject:
        return _DIFFERENT_SUBJECT_PARLAY_PAIR_PENALTY_MULTIPLIER, "different players"
    return 1.0, None


def _parlay_pair_team_multiplier(first_leg: dict[str, Any], second_leg: dict[str, Any]) -> tuple[float, str | None]:
    first_team = _candidate_team_key(first_leg)
    second_team = _candidate_team_key(second_leg)
    first_subject = _candidate_subject_key(first_leg)
    second_subject = _candidate_subject_key(second_leg)
    if first_team and second_team and first_subject and second_subject and first_subject != second_subject:
        sport_slug = _safe_text(first_leg.get("sport_slug"), "sport").lower()
        market_pair = tuple(sorted((_parlay_leg_market_key(first_leg), _parlay_leg_market_key(second_leg))))
        cluster_pair = tuple(sorted(filter(None, (_market_script_cluster(market_pair[0]), _market_script_cluster(market_pair[1])))))
        if first_team == second_team:
            override = _SAME_TEAM_SPORT_MARKET_PAIR_PENALTY_MULTIPLIERS.get((sport_slug, market_pair))
            if override is not None:
                return float(override), "same team"
            cluster_override = _SAME_TEAM_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS.get((sport_slug, cluster_pair))
            if cluster_override is not None:
                return float(cluster_override), "same team"
            return 1.0, None
        override = _OPPOSING_TEAM_SPORT_MARKET_PAIR_PENALTY_MULTIPLIERS.get((sport_slug, market_pair))
        if override is not None:
            return float(override), "opposing teams"
        cluster_override = _OPPOSING_TEAM_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS.get((sport_slug, cluster_pair))
        if cluster_override is not None:
            return float(cluster_override), "opposing teams"
        return _OPPOSING_TEAM_PARLAY_PAIR_PENALTY_MULTIPLIER, "opposing teams"
    return 1.0, None


def _format_pair_penalty_value(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _parlay_pair_feature_profile(
    first_leg: dict[str, Any],
    second_leg: dict[str, Any],
    *,
    penalty_source: str,
    script_context: str | None,
) -> dict[str, Any]:
    first_market_key = _parlay_leg_market_key(first_leg)
    second_market_key = _parlay_leg_market_key(second_leg)
    first_cluster = _market_script_cluster(first_market_key)
    second_cluster = _market_script_cluster(second_market_key)
    first_team = _candidate_team_key(first_leg)
    second_team = _candidate_team_key(second_leg)
    first_subject = _candidate_subject_key(first_leg)
    second_subject = _candidate_subject_key(second_leg)
    first_direction = _candidate_selection_direction(first_leg)
    second_direction = _candidate_selection_direction(second_leg)

    team_relationship = None
    if first_team and second_team:
        team_relationship = "same_team" if first_team == second_team else "opposing_teams"

    subject_relationship = None
    if first_subject and second_subject:
        subject_relationship = "same_player" if first_subject == second_subject else "different_players"

    direction_relationship = None
    if first_direction != 0 and second_direction != 0:
        direction_relationship = "same_direction" if first_direction == second_direction else "opposing_directions"

    cluster_pair = None
    if first_cluster and second_cluster:
        cluster_pair = [first_cluster, second_cluster]

    return {
        "penalty_source": penalty_source,
        "same_game": _safe_text(first_leg.get("matchup"), "") == _safe_text(second_leg.get("matchup"), ""),
        "team_relationship": team_relationship,
        "subject_relationship": subject_relationship,
        "direction_relationship": direction_relationship,
        "market_keys": [first_market_key, second_market_key],
        "script_cluster_pair": cluster_pair,
        "script_context": script_context,
    }


def _parlay_pair_penalty(legs: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> dict[str, Any]:
    return _runtime_parlay_pair_penalty(
        legs,
        safe_text=_safe_text,
        market_label=_market_label,
        candidate_team_key=_candidate_team_key,
        candidate_subject_key=_candidate_subject_key,
        candidate_selection_direction=_candidate_selection_direction,
        market_script_clusters=_MARKET_SCRIPT_CLUSTERS,
        pair_penalties=_PARLAY_SPORT_MARKET_PAIR_PENALTIES,
        script_cluster_pair_fallback_penalties=_SCRIPT_CLUSTER_PAIR_FALLBACK_PENALTIES,
        explicit_script_cluster_penalty_multipliers=_EXPLICIT_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS,
        script_cluster_opposing_direction_multipliers=_SCRIPT_CLUSTER_OPPOSING_DIRECTION_MULTIPLIERS,
        same_team_sport_market_pair_penalty_multipliers=_SAME_TEAM_SPORT_MARKET_PAIR_PENALTY_MULTIPLIERS,
        same_team_script_cluster_penalty_multipliers=_SAME_TEAM_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS,
        opposing_team_sport_market_pair_penalty_multipliers=_OPPOSING_TEAM_SPORT_MARKET_PAIR_PENALTY_MULTIPLIERS,
        opposing_team_script_cluster_penalty_multipliers=_OPPOSING_TEAM_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS,
        live_multiplier=_LIVE_PARLAY_PAIR_PENALTY_MULTIPLIER,
        mixed_timing_multiplier=_MIXED_TIMING_PARLAY_PAIR_PENALTY_MULTIPLIER,
        opposing_direction_multiplier=_OPPOSING_DIRECTION_PARLAY_PAIR_PENALTY_MULTIPLIER,
        different_subject_multiplier=_DIFFERENT_SUBJECT_PARLAY_PAIR_PENALTY_MULTIPLIER,
        opposing_team_multiplier=_OPPOSING_TEAM_PARLAY_PAIR_PENALTY_MULTIPLIER,
        parlay_leg_market_key_fn=_parlay_leg_market_key,
    )


def _medium_correlation_shape_limit(shape: str, sport_slug: str | None = None, market_key: str | None = None) -> int:
    sport_key = _safe_text(sport_slug, "").lower()
    market_key_value = _safe_text(market_key, "").lower()
    normalized = _safe_text(shape, "general_market") or "general_market"
    if sport_key and market_key_value:
        market_override = _MEDIUM_CORRELATION_SPORT_MARKET_LIMITS.get((sport_key, market_key_value))
        if market_override is not None:
            return int(market_override)
    if sport_key:
        override = _MEDIUM_CORRELATION_SPORT_SHAPE_LIMITS.get((sport_key, normalized))
        if override is not None:
            return int(override)
    return int(_MEDIUM_CORRELATION_SHAPE_LIMITS.get(normalized, _MEDIUM_CORRELATION_SHAPE_LIMITS["general_market"]))


def _parlay_type_label(parlay_type: str | None) -> str:
    value = _safe_text(parlay_type, "standard")
    return {
        "same_game": "same-game",
        "round_robin": "round robin",
    }.get(value, "standard")


def _parlay_label(legs: tuple[dict[str, Any], ...], preferences: dict[str, Any], *, round_robin: bool = False, ticket_index: int | None = None, ticket_total: int | None = None) -> str:
    leg_count = len(legs)
    if round_robin:
        unit = preferences.get("round_robin_unit") or leg_count
        sequence = f" ({ticket_index}/{ticket_total})" if ticket_index is not None and ticket_total is not None else ""
        return f"Round robin {unit}-leg ticket{sequence}"
    if preferences.get("parlay_type") == "same_game":
        return f"{leg_count}-leg same-game parlay"
    if preferences.get("cross_sport_required"):
        return f"{leg_count}-leg cross-sport parlay"
    return f"{leg_count}-leg {'live' if any(leg.get('is_live') for leg in legs) else 'pregame'} parlay"


def _risk_profile_stake_fraction(preferences: dict[str, Any]) -> float:
    risk_profile = _safe_text(preferences.get("risk_profile"), "balanced")
    if risk_profile == "conservative":
        return 0.02
    if risk_profile == "aggressive":
        return 0.06
    return 0.04


def _parlay_stake_plan(preferences: dict[str, Any], *, ticket_total: int | None = None) -> dict[str, Any]:
    bankroll_amount = preferences.get("bankroll_amount")
    max_exposure_pct = preferences.get("max_exposure_pct")
    max_exposure_amount = preferences.get("max_exposure_amount")
    bankroll_value = float(bankroll_amount) if bankroll_amount is not None else None
    pct_cap_amount = None
    if bankroll_value is not None and max_exposure_pct is not None:
        pct_cap_amount = round(bankroll_value * (float(max_exposure_pct) / 100.0), 2)

    effective_cap = None
    cap_source = None
    explicit_caps = [
        value
        for value in (pct_cap_amount, float(max_exposure_amount) if max_exposure_amount is not None else None)
        if value is not None
    ]
    if explicit_caps:
        effective_cap = round(min(explicit_caps), 2)
        cap_source = "requested_exposure_cap"
    elif bankroll_value is not None:
        effective_cap = round(bankroll_value * _risk_profile_stake_fraction(preferences), 2)
        cap_source = "risk_profile_bankroll"

    suggested_stake = effective_cap
    if effective_cap is not None and ticket_total and ticket_total > 1:
        suggested_stake = round(effective_cap / float(ticket_total), 2)

    stake_note = None
    if effective_cap is not None and ticket_total and ticket_total > 1:
        stake_note = f"Suggested stake ${suggested_stake:.2f} per ticket keeps the full set within a ${effective_cap:.2f} exposure cap."
    elif effective_cap is not None and cap_source == "requested_exposure_cap":
        stake_note = f"Suggested stake ${effective_cap:.2f} respects the requested exposure cap."
    elif effective_cap is not None and cap_source == "risk_profile_bankroll":
        stake_note = f"Suggested stake ${effective_cap:.2f} comes from the stated bankroll and {_safe_text(preferences.get('risk_profile'), 'balanced')} risk profile."

    return {
        "suggested_stake": suggested_stake,
        "suggested_total_exposure": effective_cap,
        "exposure_cap_amount": effective_cap,
        "exposure_cap_source": cap_source,
        "stake_note": stake_note,
    }


def _has_tight_exposure_cap(preferences: dict[str, Any]) -> bool:
    max_exposure_pct = preferences.get("max_exposure_pct")
    if max_exposure_pct is not None and float(max_exposure_pct) <= 5.0:
        return True
    bankroll_amount = preferences.get("bankroll_amount")
    max_exposure_amount = preferences.get("max_exposure_amount")
    if bankroll_amount is None or max_exposure_amount is None:
        return False
    try:
        bankroll_value = float(bankroll_amount)
        exposure_value = float(max_exposure_amount)
    except Exception:
        return False
    if bankroll_value <= 0.0:
        return False
    return (exposure_value / bankroll_value) <= 0.05


def _parlay_matches_preferences(legs: tuple[dict[str, Any], ...], preferences: dict[str, Any]) -> bool:
    return _runtime_parlay_matches_preferences(
        legs,
        preferences,
        safe_text=_safe_text,
        sport_market_pair_blocks=_MEDIUM_CORRELATION_SPORT_MARKET_PAIR_BLOCKS,
        medium_correlation_shape_limits=_MEDIUM_CORRELATION_SHAPE_LIMITS,
        medium_correlation_sport_shape_limits=_MEDIUM_CORRELATION_SPORT_SHAPE_LIMITS,
        medium_correlation_sport_market_limits=_MEDIUM_CORRELATION_SPORT_MARKET_LIMITS,
        parlay_leg_market_shape_fn=_parlay_leg_market_shape,
        parlay_leg_market_key_fn=_parlay_leg_market_key,
    )


def _build_parlay_payload(legs: tuple[dict[str, Any], ...], preferences: dict[str, Any], *, round_robin: bool = False, ticket_index: int | None = None, ticket_total: int | None = None, anchor_legs: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    return _runtime_build_parlay_payload(
        legs,
        preferences,
        round_robin=round_robin,
        ticket_index=ticket_index,
        ticket_total=ticket_total,
        anchor_legs=anchor_legs,
        candidate_summary=_candidate_summary,
        parlay_pair_penalty_fn=_parlay_pair_penalty,
        decimal_to_american=_decimal_to_american,
        american_odds_value=_american_odds_value,
        american_odds_match=_american_odds_match,
        safe_text=_safe_text,
        parlay_stake_plan=_parlay_stake_plan,
        parlay_rationale=_parlay_rationale,
        parlay_label=_parlay_label,
    )


def _parlay_rank_score(parlay: dict[str, Any], preferences: dict[str, Any]) -> float:
    parlay_with_numeric_odds = dict(parlay)
    parlay_with_numeric_odds["combined_odds"] = _american_odds_value(parlay.get("combined_odds")) or 0.0
    return _runtime_parlay_rank_score(parlay_with_numeric_odds, preferences)


def _build_round_robin_parlays(candidate_pool: list[dict[str, Any]], *, limit: int, preferences: dict[str, Any], min_leg_count: int, max_leg_count: int) -> list[dict[str, Any]]:
    return _runtime_build_round_robin_parlays(
        candidate_pool,
        limit=limit,
        preferences=preferences,
        max_leg_count=max_leg_count,
        has_tight_exposure_cap=_has_tight_exposure_cap,
        parlay_matches_preferences_fn=_parlay_matches_preferences,
        parlay_identity=_parlay_identity,
        build_parlay_payload_fn=_build_parlay_payload,
        candidate_summary=_candidate_summary,
        parlay_rank_score_fn=_parlay_rank_score,
    )


def _build_parlays(candidates: list[dict[str, Any]], *, limit: int, preferences: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return _runtime_build_parlays(
        candidates,
        limit=limit,
        preferences=preferences,
        safe_text=_safe_text,
        has_tight_exposure_cap=_has_tight_exposure_cap,
        parlay_matches_preferences_fn=_parlay_matches_preferences,
        parlay_identity=_parlay_identity,
        build_parlay_payload_fn=_build_parlay_payload,
        build_round_robin_parlays_fn=lambda candidate_pool, *, limit, preferences, max_leg_count: _build_round_robin_parlays(
            candidate_pool,
            limit=limit,
            preferences=preferences,
            min_leg_count=2,
            max_leg_count=max_leg_count,
        ),
        parlay_rank_score_fn=_parlay_rank_score,
    )


def _query_needs_mlb_home_run_candidates(preferences: dict[str, Any]) -> bool:
    requested_markets = {
        str(item).strip().lower()
        for item in (preferences.get("requested_markets") or [])
        if str(item).strip()
    }
    return preferences.get("analysis_focus") == "mlb_home_runs" or "home_runs" in requested_markets


def _has_mlb_home_run_candidates(candidates: list[dict[str, Any]]) -> bool:
    return any(
        _safe_text(candidate.get("sport_slug"), "").lower() == "mlb" and "home_runs" in _candidate_market_focuses(candidate)
        for candidate in candidates
    )


def _candidate_log_id(candidate: dict[str, Any]) -> str:
    candidate_id = (
        candidate.get("candidate_id")
        or candidate.get("recommendation_id")
        or candidate.get("prediction_id")
        or candidate.get("event_id")
        or candidate.get("id")
    )
    if candidate_id is not None and str(candidate_id).strip():
        return str(candidate_id).strip()
    sport = _safe_text(candidate.get("sport_slug") or candidate.get("sport"), "sport")
    market = _safe_text(candidate.get("market") or candidate.get("market_key"), "market")
    selection = _safe_text(candidate.get("selection") or candidate.get("pick") or candidate.get("name"), "candidate")
    return f"{sport}:{market}:{selection}"


def _candidate_filter_reason(candidate: dict[str, Any], *, selected: bool) -> str:
    if selected:
        return "ranked_in_final_picks"
    if bool(candidate.get("state_invalid")):
        return "state_invalid"
    if _candidate_is_final(candidate):
        return "final_state_excluded"
    if candidate.get("edge") is not None and _numeric_hint(candidate.get("edge")) is not None and float(_numeric_hint(candidate.get("edge")) or 0.0) <= 0.0:
        return "non_positive_edge"
    return "filtered_or_not_selected"


def _log_json_event(level: int, event: str, **fields: Any) -> None:
    if not logger.isEnabledFor(level):
        return
    payload = {"event": event, **fields}
    logger.log(level, json.dumps(payload, sort_keys=True, default=str))


def _log_candidate_pipeline(
    *,
    candidates: list[dict[str, Any]],
    filtered_candidates: list[dict[str, Any]],
    final_picks: list[dict[str, Any]],
    pipeline_name: str,
) -> None:
    candidate_ids = [_candidate_log_id(candidate) for candidate in candidates if isinstance(candidate, Mapping)]
    filtered_ids = {_candidate_log_id(candidate) for candidate in filtered_candidates if isinstance(candidate, Mapping)}
    final_ids = {_candidate_log_id(candidate) for candidate in final_picks if isinstance(candidate, Mapping)}
    _log_json_event(
        logging.INFO,
        "intelligence_candidate_pipeline_summary",
        pipeline=pipeline_name,
        total_candidates_generated=len(candidates),
        filtered_count=max(len(candidates) - len(filtered_candidates), 0),
        final_picks_count=len(final_picks),
    )
    if not logger.isEnabledFor(logging.DEBUG):
        return
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = _candidate_log_id(candidate)
        selected = candidate_id in final_ids
        payload = {
            "event": "intelligence_candidate_decision",
            "pipeline": pipeline_name,
            "candidate_id": candidate_id,
            "sport": _safe_text(candidate.get("sport"), "Sport"),
            "edge": _numeric_hint(candidate.get("edge") or candidate.get("adjusted_edge")),
            "confidence": _numeric_hint(candidate.get("confidence")),
            "selected": selected,
        }
        reason = _candidate_filter_reason(candidate, selected=selected)
        if selected:
            payload["reason_selected"] = reason
        else:
            payload["reason_filtered"] = reason
        _log_json_event(logging.DEBUG, "intelligence_candidate_decision", **payload)


def _sport_candidate_summary(candidates: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(candidate) for candidate in candidates if isinstance(candidate, Mapping)]

    def _candidate_sport(candidate: Mapping[str, Any]) -> str:
        return _safe_text(candidate.get("sport_slug") or candidate.get("sport"), "").lower() or "unknown"

    def _candidate_metrics(candidate: Mapping[str, Any]) -> dict[str, Any]:
        market_profile = candidate.get("market_profile") if isinstance(candidate.get("market_profile"), Mapping) else {}
        sport_profile = candidate.get("sport_profile") if isinstance(candidate.get("sport_profile"), Mapping) else {}
        calibration_error = _numeric_hint(market_profile.get("calibration_error"))
        if calibration_error is None:
            calibration_error = _numeric_hint(sport_profile.get("calibration_error"))
        return {
            "sport": _candidate_sport(candidate),
            "name": _safe_text(candidate.get("name"), candidate.get("pick"), candidate.get("selection"), candidate.get("player_name")),
            "score": _numeric_hint(candidate.get("score")),
            "edge": _numeric_hint(candidate.get("edge")),
            "adjusted_score": _numeric_hint(candidate.get("adjusted_score")),
            "reliability": _numeric_hint(candidate.get("performance_multiplier") or candidate.get("reliability_multiplier") or candidate.get("source_strength")),
            "calibration_error": calibration_error,
        }

    scored_rows = sorted(rows, key=lambda candidate: float(candidate.get("score") or 0.0), reverse=True)
    by_sport: dict[str, int] = {}
    top_by_sport: dict[str, list[dict[str, Any]]] = {}
    for candidate in scored_rows:
        sport_key = _candidate_sport(candidate)
        by_sport[sport_key] = by_sport.get(sport_key, 0) + 1
        bucket = top_by_sport.setdefault(sport_key, [])
        if len(bucket) < 10:
            bucket.append(_candidate_metrics(candidate))
    return {
        "total": len(rows),
        "by_sport": by_sport,
        "top_by_sport": top_by_sport,
    }


def _log_candidate_stage(
    *,
    pipeline_name: str,
    stage: str,
    before: Iterable[Mapping[str, Any]],
    after: Iterable[Mapping[str, Any]],
) -> None:
    _log_json_event(
        logging.INFO,
        "intelligence_candidate_stage",
        pipeline=pipeline_name,
        stage=stage,
        before=_sport_candidate_summary(before),
        after=_sport_candidate_summary(after),
    )


def _collect_candidate_trace(candidate: Mapping[str, Any], *, reason: str, stage: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "reason": reason,
        "sport": _safe_text(candidate.get("sport_slug") or candidate.get("sport"), "").lower(),
        "player": _safe_text(candidate.get("player_name") or candidate.get("name") or candidate.get("selection"), ""),
        "market": _safe_text(candidate.get("market") or candidate.get("market_key") or candidate.get("candidate_type"), ""),
        "selection": _safe_text(candidate.get("selection") or candidate.get("pick") or candidate.get("name"), ""),
    }


def _candidate_classification_removal_reason(candidate: Mapping[str, Any]) -> str:
    _classified, reason = _classify_candidate_with_reason(dict(candidate))
    return reason or "classification_rejected"


def collect_candidates(overview: list[dict[str, Any]], preferences: dict[str, Any], odds_history_by_sport: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if odds_history_by_sport is None:
        odds_history_by_sport = _odds_history_payloads_by_sport(overview)
    candidates = _collect_candidates(overview, preferences)
    _log_candidate_stage(pipeline_name="collect_candidates", stage="_collect_candidates", before=[], after=candidates)
    enriched_candidates = _enrich_candidates_with_odds_history(candidates, odds_history_by_sport)
    _log_candidate_stage(pipeline_name="collect_candidates", stage="_enrich_candidates_with_odds_history", before=candidates, after=enriched_candidates)
    normalized_candidates = [normalize_candidate(candidate) for candidate in enriched_candidates]
    _log_candidate_stage(pipeline_name="collect_candidates", stage="normalize_candidate", before=enriched_candidates, after=normalized_candidates)
    classified_candidates: list[dict[str, Any]] = []
    second_pass_pruned: list[dict[str, Any]] = []
    for candidate in normalized_candidates:
        classified = classify_candidate(candidate)
        if classified is None:
            second_pass_pruned.append(
                _collect_candidate_trace(candidate, reason=_candidate_classification_removal_reason(candidate), stage="second_pass_classification")
            )
            continue
        classified_candidates.append(classified)
    _log_candidate_stage(pipeline_name="collect_candidates", stage="classify_candidate", before=normalized_candidates, after=classified_candidates)
    for removed_candidate in second_pass_pruned:
        _log_json_event(logging.INFO, "collect_candidates_pruned", pipeline="collect_candidates", **removed_candidate)
    universal_candidates = [candidate for candidate in (UniversalCandidate.from_raw(classified) for classified in classified_candidates) if candidate is not None]
    _log_candidate_stage(pipeline_name="collect_candidates", stage="UniversalCandidate.from_raw", before=classified_candidates, after=universal_candidates)
    return universal_candidates


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "t", "yes", "y", "on"}


def _candidate_movement_magnitude_bonus(candidate: dict[str, Any]) -> float:
    # CLV/line-movement as a scored input (not just the display-only
    # movement/delta/odds_history fields _enrich_candidates_with_odds_history
    # already attaches). Deliberately magnitude-only, not directional: which
    # way a line moving is "favorable" depends on the candidate's own side
    # (over vs under, spread favorite vs dog, moneyline sign) and market
    # type, and getting that backwards would silently reward bad picks --
    # ruled out by design discussion on 2026-07-21. A bigger move of either
    # direction is treated as "the market is reacting to something", a
    # modest, capped confidence signal -- same cap as readiness_bonus below.
    if not _env_bool("SYNDICATE_INTELLIGENCE_SCORE_LINE_MOVEMENT", default=True):
        return 0.0
    odds_history = candidate.get("odds_history") if isinstance(candidate.get("odds_history"), dict) else {}
    percent_change = _numeric_hint(candidate.get("percent_change"))
    if percent_change is None:
        percent_change = _numeric_hint(odds_history.get("percent_change"))
    if percent_change is None:
        # Older/other-pipeline candidate shapes (e.g. pipeline/intelligence_state.py's
        # _build_candidate_pool) attach delta_line/last_line instead of a
        # precomputed percent_change -- derive the same normalized signal
        # from whatever raw values are actually present.
        delta = _numeric_hint(candidate.get("delta"))
        if delta is None:
            delta = _numeric_hint(odds_history.get("delta"))
        if delta is None:
            delta = _numeric_hint(odds_history.get("delta_line"))
        if delta is None:
            delta = _numeric_hint(candidate.get("delta_line"))
        last_line = _numeric_hint(odds_history.get("last_line"))
        if last_line is None:
            last_line = _numeric_hint(candidate.get("line"))
        if delta is not None and last_line not in (None, 0):
            percent_change = (float(delta) / abs(float(last_line))) * 100.0
    if percent_change is None:
        return 0.0
    return max(0.0, min(0.05, abs(float(percent_change)) * 0.01))


def _candidate_news_triggered_tag(candidate: dict[str, Any]) -> bool:
    # Plan item 1F0's deferred board callout: a candidate whose line/
    # projection was just regenerated because of a detected injury/lineup
    # change (syndicate.features.shared.live_refresh_loop._should_force_sim_rerun)
    # should say so distinctly, rather than looking like an ordinary
    # market-driven move (see the movement-bonus function above, which is
    # deliberately silent on *why* a line moved). Local import + broad catch:
    # this is a display-only nicety and a transient read failure of the
    # cross-process signal file must never be allowed to break scoring.
    sport_slug = _safe_text(candidate.get("sport_slug"), _safe_text(candidate.get("sport"), "")).lower()
    if not sport_slug:
        return False
    try:
        from syndicate.features.shared.live_refresh_loop import sports_with_recent_lineup_injury_change

        return sport_slug in sports_with_recent_lineup_injury_change()
    except Exception:
        return False


def score_candidate(
    candidate: dict[str, Any],
    *,
    preferences: dict[str, Any] | None = None,
    advanced_context: list[dict[str, Any]] | None = None,
    mlb_actual_cache: dict[int, dict[str, Any] | None] | None = None,
    mlb_live_lens_cache: dict[str, dict[str, Any] | None] | None = None,
    odds_payload_cache: dict[tuple[str, str], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    scored_candidate, rejection_reason = _classify_candidate_with_reason(candidate)
    if scored_candidate is None:
        # score_candidate() used to drop a failed classification silently
        # here, with only an aggregate count surfacing further up the call
        # chain (in _score_candidates' is_valid_candidate() check) -- this is
        # the third of three classify passes a candidate flows through
        # (_collect_candidates, collect_candidates, score_candidate), so a
        # reasoned trace at each one matters for diagnosing candidate drops.
        _log_json_event(
            logging.INFO,
            "collect_candidates_pruned",
            pipeline="score_candidate",
            **_collect_candidate_trace(normalize_candidate(candidate), reason=rejection_reason or "classification_rejected", stage="scoring_classification"),
        )
        return normalize_candidate(candidate)

    _apply_candidate_state_guard(scored_candidate)
    if bool(scored_candidate.get("state_invalid")):
        return scored_candidate

    has_edge = _numeric_hint(scored_candidate.get("edge")) is not None or _numeric_hint(scored_candidate.get("adjusted_edge")) is not None
    has_model_probability = _numeric_hint(scored_candidate.get("model_probability")) is not None
    has_implied_probability = _numeric_hint(scored_candidate.get("implied_probability")) is not None
    # #100: was a bare truthiness check (_safe_text(...) not in {"", "-"}),
    # the same bug class #68 fixed in _candidate_value_is_present -- a numeric
    # odds value of exactly 0 would have read as absent here. Canonicalize on
    # the shared predicate instead of a third disagreeing copy.
    has_odds = _candidate_value_is_present(scored_candidate.get("odds"))
    if has_edge and has_model_probability and has_implied_probability:
        scored_candidate["scoring_mode"] = "full"
    elif has_edge and has_odds:
        scored_candidate["scoring_mode"] = "partial"
    else:
        scored_candidate["scoring_mode"] = "minimal"

    _apply_live_state_context_to_candidates(
        [scored_candidate],
        mlb_actual_cache=mlb_actual_cache,
        mlb_live_lens_cache=mlb_live_lens_cache,
    )
    advanced_by_sport = {
        _safe_text(scored_candidate.get("sport_slug"), "sport").lower(): [dict(item) for item in (advanced_context or []) if isinstance(item, dict)]
    }
    _apply_advanced_context_to_candidates([scored_candidate], advanced_by_sport, preferences or {}, odds_payload_cache=odds_payload_cache)
    readiness_bonus = 0.0
    if advanced_context and _safe_text(scored_candidate.get("sport_slug"), "").lower() == "mlb":
        readiness = scored_candidate.get("advanced_gate") if isinstance(scored_candidate.get("advanced_gate"), dict) else {}
        readiness_ratio = _numeric_hint(readiness.get("ratio"))
        if readiness_ratio is not None:
            readiness_bonus = max(0.0, min(0.05, float(readiness_ratio) * 0.05))

    edge_value = _numeric_hint(scored_candidate.get("edge"))
    if edge_value is None:
        edge_value = _numeric_hint(scored_candidate.get("adjusted_edge"))
    if edge_value is None:
        edge_profile = _candidate_betting_edge_profile(scored_candidate)
        edge_value = _numeric_hint(edge_profile.get("edge")) if edge_profile is not None else None

    if edge_value is None:
        edge_value = 0.0

    movement_bonus = _candidate_movement_magnitude_bonus(scored_candidate)
    scored_candidate["news_triggered"] = _candidate_news_triggered_tag(scored_candidate)

    confidence_value = _numeric_hint(scored_candidate.get("source_strength"))
    if confidence_value is None:
        confidence_value = 0.5
    confidence_value = max(0.0, min(1.0, float(confidence_value) + float(readiness_bonus) + float(movement_bonus)))

    tier_penalty = {"tier_1": 0.0, "tier_2": 0.2}.get(_safe_text(scored_candidate.get("tier"), "tier_2"), 0.2)
    base_score = float(edge_value) * float(confidence_value) - float(tier_penalty)

    # _risk_profile_score_adjustment and _market_specific_score_adjustment were
    # both DEAD CODE -- defined, fully implemented, never called from anywhere.
    # So `score` was edge x confidence - tier_penalty and nothing else, which is
    # why a "highest confidence" query and a "highest upside" query returned
    # byte-identical rankings: the risk profile was parsed correctly, reached
    # preferences, and was then never consulted by the scorer. Same for a query
    # naming specific markets.
    #
    # Both are no-ops in the default case by construction -- the risk one
    # returns 0.0 unless the profile is conservative/aggressive, the market one
    # unless requested_markets is non-empty -- so this only moves rankings for
    # queries that actually expressed a preference.
    #
    # Worked example (the two candidates in the risk fixture), showing the
    # adjustments are sized to matter without swamping the base score:
    #   base:         Judge 6.2   Freeman 1.05
    #   conservative: Judge 2.74  Freeman 3.80  -> Freeman, the 64%/-135 pick
    #   aggressive:   Judge 13.32 Freeman 0.84  -> Judge, the 38%/+320 pick
    scoring_preferences = preferences or {}
    market_context = scored_candidate.get("market_context")
    if not isinstance(market_context, dict):
        market_context = _market_context(scored_candidate)
    base_score += _risk_profile_score_adjustment(scored_candidate, scoring_preferences, market_context)
    base_score += _market_specific_score_adjustment(scored_candidate, scoring_preferences, market_context)

    scored_candidate["score"] = round(base_score, 4)
    return scored_candidate


def _score_candidates(
    candidates: list[dict[str, Any]],
    advanced_by_sport: dict[str, list[dict[str, Any]]],
    preferences: dict[str, Any],
    *,
    pipeline: str | None = None,
) -> list[dict[str, Any]]:
    score_started_at = time.perf_counter()
    scored_candidates: list[dict[str, Any]] = []
    state_invalid_filtered = 0
    final_filtered = 0
    # Shared across the whole batch (not per-candidate) so each unique MLB
    # game_pk's raw feed file and each date's live-lens report get read from
    # disk once per scoring pass instead of once per candidate.
    mlb_actual_cache: dict[int, dict[str, Any] | None] = {}
    mlb_live_lens_cache: dict[str, dict[str, Any] | None] = {}
    # Same batch-scoped sharing for the odds-history shard payload
    # score_candidate's simulation-context build reads per candidate --
    # confirmed in production 2026-07-24 that scoping this cache one level
    # too low (inside _apply_advanced_context_to_candidates, which
    # score_candidate calls with a fresh single-item list every time) made it
    # a no-op: a cache that's recreated before every single candidate never
    # gets reused across candidates, so it must be created here instead.
    odds_payload_cache: dict[tuple[str, str], dict[str, Any] | None] = {}
    for candidate in candidates:
        scored_candidate = score_candidate(
            candidate,
            preferences=preferences,
            advanced_context=advanced_by_sport.get(_safe_text(candidate.get("sport_slug"), "sport").lower(), []),
            mlb_actual_cache=mlb_actual_cache,
            mlb_live_lens_cache=mlb_live_lens_cache,
            odds_payload_cache=odds_payload_cache,
        )
        if not is_valid_candidate(scored_candidate):
            continue
        if _candidate_is_final(scored_candidate) or bool(scored_candidate.get("state_invalid")):
            if bool(scored_candidate.get("state_invalid")):
                state_invalid_filtered += 1
            else:
                final_filtered += 1
            continue
        scored_candidates.append(scored_candidate)
    sport_counts: dict[str, int] = {}
    market_counts: dict[str, int] = {}
    for candidate in scored_candidates:
        sport_key = _safe_text(candidate.get("sport_slug"), _safe_text(candidate.get("sport"), "sport")).lower() or "sport"
        sport_counts[sport_key] = sport_counts.get(sport_key, 0) + 1
        market_key = _safe_text(candidate.get("candidate_type") or candidate.get("type"), "candidate").lower() or "candidate"
        market_counts[market_key] = market_counts.get(market_key, 0) + 1
    _intel_trace_timed(
        "candidate_scoring",
        score_started_at,
        pipeline=pipeline,
        input_count=len(candidates),
        output_count=len(scored_candidates),
        state_invalid_filtered=state_invalid_filtered,
        final_filtered=final_filtered,
        by_sport=sport_counts,
        by_market=market_counts,
    )
    return scored_candidates


def filter_candidates(
    candidates: list[dict[str, Any]],
    *,
    sport: str | None = None,
    ledger_path: Path | str | None = None,
    evaluation_records: Iterable[Mapping[str, Any]] | None = None,
    policy: str | None = None,
    min_edge: float = 0.0,
) -> list[dict[str, Any]]:
    return _shared_filter_candidates(
        candidates,
        sport=sport,
        ledger_path=ledger_path,
        evaluation_records=evaluation_records,
        policy=policy,
        min_edge=min_edge,
    )


def rank_candidates(
    candidates: list[dict[str, Any]],
    *,
    sport: str | None = None,
    ledger_path: Path | str | None = None,
    evaluation_records: Iterable[Mapping[str, Any]] | None = None,
    policy: str | None = None,
    experiment_key: str | None = None,
    limit: int | None = None,
    ranking_key: Any | None = None,
) -> list[dict[str, Any]]:
    ranked_candidates = _shared_rank_recommendations(
        candidates,
        sport=sport,
        ledger_path=ledger_path,
        evaluation_records=evaluation_records,
        policy=policy,
        experiment_key=experiment_key,
        limit=limit,
    )
    if ranking_key is None:
        return ranked_candidates
    custom_ranked = sorted([dict(candidate) for candidate in candidates if isinstance(candidate, Mapping)], key=ranking_key, reverse=True)
    if limit is not None:
        return custom_ranked[: max(0, int(limit))]
    return custom_ranked


def collect_all_recommendations(
    *,
    selected_date: str | None = None,
    force_refresh: bool = False,
    log_pipeline: bool = True,
    overview: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    effective_date = _effective_date(selected_date or central_today_iso())
    # overview: lets a caller that already built one (e.g.
    # collect_candidates_with_fallback_merge's fallback/thin-pool-merge
    # branches, which already have overview as a parameter) skip
    # build_intelligence_overview's own per-sport artifact-status/existence
    # checks entirely instead of silently re-running them -- confirmed via
    # production diagnostic that this fallback path re-fetches on every
    # candidate-collection cycle (not just as a rare fallback), doubling
    # boot-time artifact-file I/O and contributing to container memory
    # pressure (page cache, not process RSS) that was OOM-killing the
    # refresh-worker within 1-2 minutes of boot.
    if overview is None:
        overview = build_intelligence_overview(selected_date=effective_date, force_refresh=force_refresh)
    odds_history_by_sport = _odds_history_payloads_by_sport(overview)
    tracked = _tracked_repo_files()
    preferences = _query_preferences(
        "top edges today",
        mode="recommendation",
        sport="all",
        timing="all",
        include_props=True,
        include_games=True,
    )
    advanced_by_sport = {
        _safe_text(sport_row.get("slug"), "sport").lower(): _advanced_input_rows_for_sport(sport_row, tracked)
        for sport_row in overview
        if isinstance(sport_row, dict)
    }
    candidate_started_at = time.perf_counter()
    candidates = _primary_query_candidates(overview, preferences, odds_history_by_sport)
    _intel_trace_timed("candidate_collection", candidate_started_at, pipeline="collect_all_recommendations", candidate_count=len(candidates))
    scoring_started_at = time.perf_counter()
    candidates = _enrich_candidates_with_odds_history(candidates, odds_history_by_sport)
    candidates = _score_candidates(candidates, advanced_by_sport, preferences, pipeline="collect_all_recommendations")
    _intel_trace_timed("scoring", scoring_started_at, pipeline="collect_all_recommendations", candidate_count=len(candidates))
    ranking_started_at = time.perf_counter()
    filtered_candidates = filter_candidates(candidates, sport=_safe_text(preferences.get("sport"), "") or None)
    ranked_recommendations = _balanced_recommendation_order(filtered_candidates)
    if not ranked_recommendations:
        ranked_recommendations = _balanced_recommendation_order(candidates)
    _intel_trace_timed("ranking", ranking_started_at, pipeline="collect_all_recommendations", recommendation_count=len(ranked_recommendations))
    _intel_trace(
        "opportunity_generation",
        pipeline="collect_all_recommendations",
        total_candidates=len(candidates),
        filtered_candidates=len(filtered_candidates),
        opportunities=len(ranked_recommendations),
    )
    if log_pipeline:
        _log_candidate_pipeline(
            candidates=candidates,
            filtered_candidates=filtered_candidates,
            final_picks=ranked_recommendations,
            pipeline_name="collect_all_recommendations",
        )
    return [dict(recommendation) for recommendation in ranked_recommendations if isinstance(recommendation, dict)]


def candidate_identity_key(candidate: dict[str, Any]) -> str:
    # Extracted from IntelligenceStateService._candidate_id (pipeline/intelligence_state.py)
    # so collect_candidates_with_fallback_merge below can dedupe/union candidates
    # without needing a service instance. That method now delegates here.
    identifier = {
        "sport_slug": str(candidate.get("sport_slug") or candidate.get("sport") or "").strip().lower(),
        "candidate_type": str(candidate.get("candidate_type") or "").strip().lower(),
        "event_id": str(candidate.get("event_id") or "").strip(),
        "game_pk": str(candidate.get("game_pk") or candidate.get("gamePk") or "").strip(),
        "subject_key": str(candidate.get("subject_key") or candidate.get("player_name") or candidate.get("name") or "").strip().lower(),
        "market_key": str(candidate.get("market_key") or candidate.get("market") or "").strip().lower(),
        "selection": str(candidate.get("selection") or candidate.get("pick") or "").strip().lower(),
        "line": str(candidate.get("line") or candidate.get("market_line") or candidate.get("prop_line") or "").strip().lower(),
        "odds": str(candidate.get("odds") or candidate.get("odds_current") or "").strip().lower(),
    }
    canonical = json.dumps(identifier, sort_keys=True, separators=(",", ":"), default=str)
    return f"cand_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]}"


_THIN_CANDIDATE_POOL_THRESHOLD = 20


def collect_candidates_with_fallback_merge(
    overview: list[dict[str, Any]],
    preferences: dict[str, Any],
    odds_history_by_sport: dict[str, dict[str, Any]] | None = None,
    *,
    selected_date: str | None = None,
    apply_edge_filter: bool = True,
    apply_thin_pool_merge: bool = True,
    advanced_by_sport: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Single collect-with-fallback entry point, extracted from
    IntelligenceStateService._build_candidate_pool so every caller gets the
    same behavior instead of only the board-publication path having it.

    collect_candidates (the primary path) and collect_all_recommendations
    (the fallback) don't always agree on completeness -- confirmed live
    2026-07-21: collect_candidates returning a non-empty but thin result
    (e.g. 10) permanently skipped the richer fallback (which found 181 for
    the identical date/sport), because an "if not raw_candidates" check
    only ever fires on a literal empty list. A fresh direct compute minutes
    apart, same payload, same underlying data, produced 10 vs 181 -- not a
    timing artifact. Try the richer pipeline whenever the primary result
    looks suspiciously thin (not just when it's empty), and keep whichever
    is actually bigger -- or, when both have non-overlapping coverage,
    union them (see below) rather than picking one.

    apply_edge_filter=False for callers (like run_intelligence_query) that
    already run their own scoring/filtering downstream on the raw pool --
    applying it here too would double-gate.

    apply_thin_pool_merge=False for callers whose primary result is
    intentionally narrow/curated rather than a broad "everything available"
    pool -- e.g. run_intelligence_query's own focused queries ("best home
    run matchups today"), where the primary candidates ARE the whole
    answer. Confirmed regression: unioning a 1-candidate curated HR-board
    result with collect_all_recommendations' broad, unrelated pool passed
    the thin-count check (1 < 20) and silently changed which candidates
    the downstream subject/market-focused analysis view was built from,
    losing the "home runs board" headline entirely. Only the empty-pool
    fallback above still applies for these callers -- a pool with zero
    candidates is never intentional.
    """
    raw_candidates = collect_candidates(overview, preferences, odds_history_by_sport)
    if not raw_candidates:
        try:
            # collect_all_recommendations() already runs _score_candidates()
            # + filter_candidates() internally, so it doesn't need the
            # explicit scoring/filtering step below applied a second time.
            raw_candidates = collect_all_recommendations(
                selected_date=selected_date,
                force_refresh=True,
                log_pipeline=False,
                overview=overview,
            )
        except TypeError:
            raw_candidates = []
    elif apply_edge_filter:
        if advanced_by_sport is None:
            tracked = _tracked_repo_files()
            advanced_by_sport = {
                _safe_text(sport_row.get("slug"), "sport").lower(): _advanced_input_rows_for_sport(sport_row, tracked)
                for sport_row in overview
                if isinstance(sport_row, dict)
            }
        scored_candidates = _score_candidates(raw_candidates, advanced_by_sport, preferences, pipeline="collect_candidates_with_fallback_merge")
        raw_candidates = filter_candidates(scored_candidates, sport=None)

    if apply_thin_pool_merge and 0 < len(raw_candidates) < _THIN_CANDIDATE_POOL_THRESHOLD:
        try:
            richer_candidates = collect_all_recommendations(
                selected_date=selected_date,
                force_refresh=True,
                log_pipeline=False,
                overview=overview,
            )
        except TypeError:
            richer_candidates = []
        richer_candidates = [c for c in richer_candidates if isinstance(c, Mapping)]
        if len(richer_candidates) > len(raw_candidates):
            # Merge, don't replace: confirmed live 2026-07-21 that a wholesale
            # swap loses coverage whenever the two pipelines don't have
            # identical sport reach -- MLB came back at the richer pipeline's
            # 181-candidate count, but WNBA (present in the primary result)
            # disappeared entirely from the combined board. Union both pools
            # by candidate identity so a sport/candidate either pipeline
            # uniquely finds survives instead of one silently overwriting
            # the other's coverage.
            merged_by_id: dict[str, dict[str, Any]] = {}
            for source in (raw_candidates, richer_candidates):
                for candidate in source:
                    candidate = dict(candidate)
                    try:
                        identity = candidate_identity_key(candidate)
                    except Exception:
                        identity = ""
                    key = identity or f"_unkeyed_{id(candidate)}"
                    merged_by_id.setdefault(key, candidate)
            raw_candidates = list(merged_by_id.values())
            # Board-alignment audit, found live 2026-08-01 against a real
            # live WNBA game: candidate_identity_key hashes exact field text
            # (selection/line/odds verbatim, not normalized) -- by design,
            # it's meant to dedupe a pipeline against re-running itself, not
            # to reconcile two DIFFERENT pipelines' representations of the
            # same real-world bet ("Alyssa Thomas UNDER 8.5" vs "UNDER" as
            # selection text hash to different keys even for the identical
            # player/market/line). setdefault() above keeps whichever
            # candidate it saw first and permanently discards the other --
            # no backfill, no reconciliation -- so when raw_candidates (the
            # primary, correctly-live-hydrated pipeline) and richer_candidates
            # (the fallback/analytical pipeline) both cover the same real
            # prop, exactly which one survives is arbitrary, and the loser's
            # live_projection/actual is gone even though a live-hydrated
            # twin existed. _merge_duplicate_prop_candidates' looser,
            # cross-pipeline-aware identity (_prop_merge_dedup_key) already
            # solves exactly this for _collect_candidates' own output --
            # running it again here catches the union-introduced duplicates
            # candidate_identity_key's stricter hash lets through. Never
            # touch candidate_identity_key itself for this: the same
            # function backs the persistent evaluation ledger's candidate
            # IDs (IntelligenceStateService._candidate_id), where a looser
            # hash would risk conflating genuinely different historical bets.
            raw_candidates = _merge_duplicate_prop_candidates(raw_candidates)

    return [candidate for candidate in raw_candidates if isinstance(candidate, Mapping)]


def rank_global_recommendations(recommendations: list[dict[str, Any]], *, limit: int | None = None) -> list[dict[str, Any]]:
    ranked = sorted(
        [dict(recommendation) for recommendation in recommendations if isinstance(recommendation, Mapping)],
        key=lambda recommendation: float(recommendation.get("score") or 0.0),
        reverse=True,
    )
    if limit is None:
        return ranked
    return ranked[: max(int(limit), 0)]


def _recommendation_market_key(recommendation: dict[str, Any]) -> str:
    return _safe_text(recommendation.get("market"), "") or _safe_text(recommendation.get("candidate_type"), "candidate")


def _balanced_market_order(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Round-robin by market within a single sport bucket. Without this, one
    market family (e.g. every hitter's "Under 0.5 Hits" prop) can
    systematically score the highest edge and crowd out every other market
    before diversity gets a look -- confirmed in production where 6 of 10
    MLB candidates were the identical "Under 0 Hits" pick.
    """
    if len(recommendations) < 2:
        return list(recommendations)
    market_buckets: dict[str, list[dict[str, Any]]] = {}
    for recommendation in recommendations:
        market_buckets.setdefault(_recommendation_market_key(recommendation), []).append(recommendation)
    if len(market_buckets) < 2:
        return list(recommendations)
    market_order = sorted(
        market_buckets,
        key=lambda market_key: _candidate_betting_rank_key(market_buckets[market_key][0]),
        reverse=True,
    )
    balanced: list[dict[str, Any]] = []
    index = 0
    while len(balanced) < len(recommendations):
        advanced = False
        for market_key in market_order:
            bucket = market_buckets.get(market_key) or []
            if index >= len(bucket):
                continue
            balanced.append(bucket[index])
            advanced = True
            if len(balanced) >= len(recommendations):
                break
        if not advanced:
            break
        index += 1
    return balanced or list(recommendations)


def _balanced_recommendation_order(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = rank_global_recommendations(recommendations, limit=None)
    if len(ranked) < 2:
        return ranked

    sport_buckets: dict[str, list[dict[str, Any]]] = {}
    for recommendation in ranked:
        sport_key = _safe_text(recommendation.get("sport_slug") or recommendation.get("sport"), "sport").lower()
        sport_buckets.setdefault(sport_key, []).append(recommendation)

    sport_order = sorted(
        sport_buckets,
        key=lambda sport_key: _candidate_betting_rank_key(sport_buckets[sport_key][0]),
        reverse=True,
    )
    for sport_key, bucket in sport_buckets.items():
        # Used to sort by is_live first, betting quality second -- every
        # live candidate, no matter how weak, outranked every pregame
        # candidate, no matter how strong, within a sport bucket. Since
        # _balanced_market_order below (and the outer round-robin across
        # sport buckets) only ever draws from the FRONT of each bucket up to
        # however many slots the board actually shows, a sport with several
        # live candidates could crowd out its own genuinely better pregame
        # candidates entirely -- confirmed live 2026-07-23 while
        # investigating why WNBA's pregame candidates were missing from the
        # served board. Betting quality (edge/confidence/score) is the only
        # thing that should decide order here, matching how ranking works
        # everywhere else in this module (e.g. _greedy_low_correlation_selection).
        bucket.sort(key=_candidate_betting_rank_key, reverse=True)
        sport_buckets[sport_key] = _balanced_market_order(bucket)

    if len(sport_buckets) < 2:
        return next(iter(sport_buckets.values()), ranked)

    balanced: list[dict[str, Any]] = []
    index = 0
    while len(balanced) < len(ranked):
        advanced = False
        for sport_key in sport_order:
            bucket = sport_buckets.get(sport_key) or []
            if index >= len(bucket):
                continue
            balanced.append(bucket[index])
            advanced = True
            if len(balanced) >= len(ranked):
                break
        if not advanced:
            break
        index += 1

    return balanced or ranked


def _build_board_dictionary(recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    board: dict[str, Any] = {
        "top_overall": [],
        "by_sport": {},
        "live": [],
        "pregame": [],
        "props": [],
        "games": [],
        "parlays": [],
    }
    by_sport = board["by_sport"]
    for recommendation in recommendations:
        if not isinstance(recommendation, Mapping):
            continue
        item = dict(recommendation)
        board["top_overall"].append(item)
        sport_name = _safe_text(item.get("sport"), _safe_text(item.get("sport_slug"), "unknown"))
        by_sport.setdefault(sport_name, []).append(item)
        if bool(item.get("is_live")):
            board["live"].append(item)
        else:
            board["pregame"].append(item)
        candidate_type = _safe_text(item.get("type"), _safe_text(item.get("candidate_type"), "")).lower()
        if candidate_type == "prop":
            board["props"].append(item)
        elif candidate_type == "game":
            board["games"].append(item)
        elif candidate_type == "parlay":
            board["parlays"].append(item)
    _intel_trace(
        "board_input",
        opportunities_received=len(recommendations),
        lane_counts={
            "live": len(board["live"]),
            "pregame": len(board["pregame"]),
            "props": len(board["props"]),
            "games": len(board["games"]),
            "parlays": len(board["parlays"]),
        },
    )
    return board


def run_intelligence_query(
    question: str,
    *,
    selected_date: str | None = None,
    mode: str | None = None,
    sport: str | None = None,
    game_state: str | None = None,
    limit: int | None = None,
    timing: str | None = None,
    include_props: bool | None = None,
    include_games: bool | None = None,
    policy: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    request_started_at = time.perf_counter()
    preferences = _query_preferences(
        question,
        mode=mode,
        sport=sport,
        game_state=game_state,
        limit=limit,
        timing=timing,
        include_props=include_props,
        include_games=include_games,
        policy=policy,
    )
    effective_date = _effective_date(selected_date or preferences.get("requested_date"))
    overview = build_intelligence_overview(selected_date=effective_date, force_refresh=force_refresh)
    odds_history_by_sport = _odds_history_payloads_by_sport(overview)
    tracked = _tracked_repo_files()
    advanced_by_sport = {
        _safe_text(sport_row.get("slug"), "sport").lower(): _advanced_input_rows_for_sport(sport_row, tracked)
        for sport_row in overview
        if isinstance(sport_row, dict)
    }
    cache_key = _query_cache_key(
        question=question,
        selected_date=effective_date,
        mode=mode,
        sport=sport,
        game_state=game_state,
        limit=limit,
        timing=timing,
        include_props=include_props,
        include_games=include_games,
        policy=preferences.get("policy"),
        overview=overview,
    )
    if not force_refresh:
        cached_response = _read_cached_query_response(cache_key)
        if cached_response is not None and not (
            isinstance(cached_response.get("analysis_views"), dict)
            and isinstance(cached_response.get("analysis_brief"), dict)
            and isinstance(cached_response.get("parsed_request"), dict)
        ):
            cached_response = None
        if cached_response is not None:
            _intel_trace_timed(
                "response_assembly",
                request_started_at,
                pipeline="run_intelligence_query",
                cache_hit=True,
                recommendation_count=len(cached_response.get("recommendations") or []),
            )
            return cached_response
    candidate_started_at = time.perf_counter()
    # apply_edge_filter=False: this function already runs its own
    # _score_candidates()/filter_candidates() below (after subject/market
    # resolution) -- applying the edge gate here too would double-gate.
    # apply_thin_pool_merge=False: this function's questions are often
    # intentionally narrow/curated (e.g. "best home run matchups today"),
    # so a thin-but-correct primary result must not get unioned with
    # collect_all_recommendations' broad, unrelated pool -- only fall back
    # when the primary pool is genuinely empty.
    candidates = collect_candidates_with_fallback_merge(
        overview,
        preferences,
        odds_history_by_sport,
        selected_date=effective_date,
        apply_edge_filter=False,
        apply_thin_pool_merge=False,
        advanced_by_sport=advanced_by_sport,
    )
    _intel_trace_timed("candidate_generation", candidate_started_at, pipeline="run_intelligence_query", candidate_count=len(candidates))
    _log_candidate_stage(pipeline_name="run_intelligence_query", stage="collect_candidates", before=[], after=candidates)
    resolved_requested_subjects = _resolved_requested_subjects(question, candidates)
    if resolved_requested_subjects != (preferences.get("requested_subjects") or []):
        preferences = {**preferences, "requested_subjects": resolved_requested_subjects}
        candidates = _filter_candidates_to_requested_subjects(candidates, resolved_requested_subjects)
    resolved_requested_markets = _resolved_requested_markets(question, candidates, preferences.get("requested_markets") or [])
    if resolved_requested_markets != (preferences.get("requested_markets") or []):
        preferences = {**preferences, "requested_markets": resolved_requested_markets}
        candidates = _filter_candidates_to_requested_markets(candidates, resolved_requested_markets)
    resolved_analysis_focus = _analysis_focus_from_resolved_candidates(question, candidates, preferences)
    if resolved_analysis_focus and resolved_analysis_focus != preferences.get("analysis_focus"):
        preferences = {**preferences, "analysis_focus": resolved_analysis_focus}
    scoring_started_at = time.perf_counter()
    pre_enrich_candidates = [dict(candidate) for candidate in candidates if isinstance(candidate, Mapping)]
    candidates = _enrich_candidates_with_odds_history(candidates, odds_history_by_sport)
    _log_candidate_stage(pipeline_name="run_intelligence_query", stage="_enrich_candidates_with_odds_history", before=pre_enrich_candidates, after=candidates)
    pre_score_candidates = [dict(candidate) for candidate in candidates if isinstance(candidate, Mapping)]
    candidates = _score_candidates(candidates, advanced_by_sport, preferences, pipeline="run_intelligence_query")
    _log_candidate_stage(pipeline_name="run_intelligence_query", stage="_score_candidates", before=pre_score_candidates, after=candidates)
    _intel_trace_timed("scoring", scoring_started_at, pipeline="run_intelligence_query", candidate_count=len(candidates))
    ranking_started_at = time.perf_counter()
    pre_filter_candidates = [dict(candidate) for candidate in candidates if isinstance(candidate, Mapping)]
    filtered_candidates = filter_candidates(candidates, sport=_safe_text(preferences.get("sport"), "") or None)
    # An explicitly requested subject must survive the edge gate: "Compare
    # Judge vs Ohtani" is a question about both players, and answering with
    # only the one that clears the board threshold silently rewrites it.
    # The gate still applies to everything the question didn't name.
    requested_subject_keys = {str(item).strip().lower() for item in (preferences.get("requested_subjects") or []) if str(item).strip()}
    if requested_subject_keys:
        # Re-add by SUBJECT, not by row: the gate's survivors are copies with
        # normalized fields, so row-level identity can't be trusted, and the
        # invariant is "each requested subject survives", not "every one of
        # its rows does".
        gated_subjects = {_candidate_subject_key(candidate) for candidate in filtered_candidates}
        for candidate in candidates:
            subject = _candidate_subject_key(candidate) or ""
            if subject in requested_subject_keys and subject not in gated_subjects:
                filtered_candidates.append(candidate)
                gated_subjects.add(subject)
    _log_candidate_stage(pipeline_name="run_intelligence_query", stage="filter_candidates", before=pre_filter_candidates, after=filtered_candidates)
    pre_balance_candidates = [dict(candidate) for candidate in filtered_candidates if isinstance(candidate, Mapping)]
    ranked_recommendations = _balanced_recommendation_order(filtered_candidates)
    _log_candidate_stage(pipeline_name="run_intelligence_query", stage="_balanced_recommendation_order", before=pre_balance_candidates, after=ranked_recommendations)
    if not ranked_recommendations:
        ranked_recommendations = _balanced_recommendation_order(candidates)
    _intel_trace_timed("ranking", ranking_started_at, pipeline="run_intelligence_query", recommendation_count=len(ranked_recommendations))
    evaluation_started_at = time.perf_counter()
    pre_selection_recommendations = [dict(candidate) for candidate in ranked_recommendations if isinstance(candidate, Mapping)]
    # Was _greedy_low_correlation_selection(..., limit=len(ranked_recommendations)).
    # That limit was already a no-op (set to the full length), but the
    # correlation-threshold EXCLUSION inside it was not: it silently
    # dropped any candidate scoring >0.65 "correlated" (same game/subject)
    # with one already kept, which collapsed pools of 100+ real per-sport
    # candidates down to ~5 -- not a numeric cap anywhere, but the same
    # user-visible effect ("still only see 10 candidates"). Correlation
    # exclusion is the right tool for building one parlay ticket's legs,
    # which _build_parlays below already does independently (from
    # filtered_candidates, with its own correlation check in
    # intelligence_parlay_runtime.py) -- it was never needed here too. The
    # board should show every real candidate; _balanced_recommendation_order
    # above already keeps the most differentiated picks (by sport and
    # market family) at the front for any client that only renders the
    # first N, without dropping the rest.
    recommendations = [dict(candidate) for candidate in ranked_recommendations]
    # Odds-window preferences (plus-money-only, favorite floor, explicit
    # min/max) parsed from the question apply to the flat recommendations,
    # not only to parlay legs -- _american_odds_match was otherwise consumed
    # solely by the parlay runtime, so "plus money only" requests still
    # served minus-odds picks. Candidates with no parseable odds pass only
    # when no odds preference was expressed, matching the helper's contract.
    if any(
        preferences.get(key) is not None and preferences.get(key) is not False
        for key in ("plus_money_only", "candidate_odds_min", "candidate_odds_max", "favorite_floor")
    ):
        recommendations = [
            candidate
            for candidate in recommendations
            if _american_odds_match(_american_odds_value(candidate.get("odds")), preferences)
        ]
    # Same for the timing preference: live_only/pregame_only previously only
    # nudged scoring, so an explicit timing=live request still served pregame
    # picks. These flags are only set when the caller (or the question)
    # expressed a timing, so strict filtering is the requested behavior.
    if preferences.get("live_only"):
        recommendations = [candidate for candidate in recommendations if bool(candidate.get("is_live"))]
    elif preferences.get("pregame_only"):
        recommendations = [candidate for candidate in recommendations if not bool(candidate.get("is_live"))]
    _log_candidate_stage(pipeline_name="run_intelligence_query", stage="_greedy_low_correlation_selection", before=pre_selection_recommendations, after=recommendations)
    _intel_trace_timed("evaluation", evaluation_started_at, pipeline="run_intelligence_query", recommendation_count=len(recommendations))
    _intel_trace(
        "opportunity_generation",
        pipeline="run_intelligence_query",
        total_candidates=len(candidates),
        filtered_candidates=len(filtered_candidates),
        ranked_candidates=len(ranked_recommendations),
        opportunities=len(recommendations),
    )
    for recommendation in recommendations:
        if not recommendation.get("advanced_inputs") and recommendation.get("advanced_context"):
            recommendation["advanced_inputs"] = recommendation.get("advanced_context")
        artifact_features = recommendation.get("artifact_features") if isinstance(recommendation.get("artifact_features"), dict) else {}
        if artifact_features:
            recommendation["artifact_features"] = dict(artifact_features)
            recommendation["feature_coverage"] = dict(artifact_features.get("feature_coverage") or recommendation.get("feature_coverage") or {})
        coverage_profile = build_feature_coverage_profile(recommendation.get("feature_coverage") or (artifact_features.get("feature_coverage") if artifact_features else {}))
        if coverage_profile:
            recommendation["model_confidence"] = recommendation.get("confidence")
            recommendation.update(coverage_profile)
            if recommendation.get("coverage_adjusted_confidence") is not None:
                recommendation["confidence"] = recommendation.get("coverage_adjusted_confidence")
    _log_candidate_pipeline(
        candidates=candidates,
        filtered_candidates=filtered_candidates,
        final_picks=recommendations,
        pipeline_name="run_intelligence_query",
    )
    # #72 (2026-07-27): the per-query prediction-ledger write is GONE, on the
    # user's decision that the ledger is obsolete. What it did: for every
    # recommendation of every intelligence query, record_prediction() appended
    # ~14.5KB to data/prediction_ledger.json and REWROTE THE WHOLE FILE --
    # measured at 2.5MB and growing, on the request path of a 2-thread web
    # service (#56), while its only automated reader
    # (pipeline/performance_aggregator.py) reported
    # used_prediction_ledger_fallback: false / prediction_ledger_count: 0.
    # Written on every request, read by nobody, cost growing with age.
    #
    # Deliberately NOT removed: the explicit write in
    # syndicate/blueprints/intelligence.py (/api/portfolio/bets) -- that is a
    # user-submitted bet, bounded by user action, and /portfolio genuinely
    # reads it through portfolio_summary.py. Same file, different feature.
    # The prediction_ledger module itself stays for that path.
    response_started_at = time.perf_counter()
    parlay_limit = preferences["limit"] if preferences.get("parlay_type") == "round_robin" else min(3, preferences["limit"])
    parlays = _build_parlays(filtered_candidates, limit=parlay_limit, preferences=preferences) if preferences.get("intent") == "parlay" or "parlay" in preferences.get("question", "").lower() else []
    analysis_views = _analysis_views_for_query(candidates, preferences)
    supporting_evidence = _build_supporting_evidence(recommendations, analysis_views, display_limit=preferences["limit"])
    analysis_brief = _build_analysis_brief(
        recommendations,
        analysis_views,
        supporting_evidence,
        preferences=preferences,
    )

    live_rows = sum(1 for candidate in candidates if bool(candidate.get("is_live")))
    pregame_rows = sum(1 for candidate in candidates if not bool(candidate.get("is_live")))
    data_notes = []
    for sport_row in overview:
        warnings = [str(item).strip() for item in (sport_row.get("data_warnings") or []) if str(item).strip()]
        if warnings:
            data_notes.append(f"{_safe_text(sport_row.get('name'), 'Sport')}: {'; '.join(warnings)}")
        sport_slug = _safe_text(sport_row.get("slug"), "sport").lower()
        advanced_rows = [row for row in advanced_by_sport.get(sport_slug, []) if bool(row.get("exists"))]
        advanced_driver_text = _advanced_driver_text(advanced_rows, limit_groups=1, limit_metrics=4)
        if advanced_driver_text:
            data_notes.append(f"{_safe_text(sport_row.get('name'), 'Sport')} advanced inputs: {advanced_driver_text}")
        readiness = _advanced_readiness_summary(advanced_by_sport.get(sport_slug, []))
        if readiness.get("missing_inputs"):
            missing_labels = ", ".join(item.get("label") or "input" for item in readiness.get("missing_inputs", [])[:3])
            data_notes.append(f"{_safe_text(sport_row.get('name'), 'Sport')} missing advanced inputs: {missing_labels}")

    readiness_gate = _build_readiness_gate(overview, tracked)

    # Specific headlines outrank generic lane headlines. The live/pregame
    # branches used to sit above these, so "the best points targets across NBA
    # and WNBA" came back as "The Syndicate pregame board brief" -- the lane is
    # not what the user asked about, and the question named a market.
    #
    # The lane wins far more often than it looks like it should, which is why
    # this mattered: the router classifies a question like this as
    # player_analysis and _pipeline_mode_for_query_type maps that to "pregame",
    # which becomes timing="pregame" and flips intent to pregame_bets -- a
    # timing the caller never sent. Rather than unpick that inference (it feeds
    # routing elsewhere), let the more specific headline win, which is the
    # behaviour these branches were clearly written for: comparison and market
    # headlines name the actual subject, the lane ones are fallbacks.
    headline = "The Syndicate brief"
    if preferences["intent"] == "parlay":
        headline = "The Syndicate parlay builder"
    elif preferences.get("comparison_requested") and len(preferences.get("requested_subjects") or []) >= 2:
        compared = [" ".join(part.capitalize() for part in str(subject).split()) for subject in (preferences.get("requested_subjects") or [])[:2]]
        headline = f"The Syndicate comparison: {compared[0]} vs {compared[1]}"
    elif preferences.get("requested_markets"):
        first_market = _market_label((preferences.get("requested_markets") or [None])[0]).lower()
        headline = f"The Syndicate {first_market} board"
    elif preferences["intent"] == "live_bets":
        headline = "The Syndicate live board brief"
    elif preferences["intent"] == "pregame_bets":
        headline = "The Syndicate pregame board brief"

    summary = (
        f"Scanned {len(candidates)} board candidates across {len([sport_row for sport_row in overview if _sport_matches_preferences(sport_row, preferences)]) or len(overview)} sports. "
        f"Live candidates: {live_rows}. Pregame candidates: {pregame_rows}."
    )
    structured_response = _build_structured_answer(
        {
            "selected_date": effective_date,
            "summary": summary,
            "local_only": True,
        },
        recommendations,
        analysis_views,
        supporting_evidence,
        data_notes[:8],
        readiness_gate,
        overview,
    )
    final_response = build_response(recommendations=recommendations, parlays=parlays)
    final_response["selected_date"] = effective_date
    final_response["query_type"] = preferences.get("intent") or preferences.get("query_type")
    final_response["parsed_request"] = dict(preferences)
    final_response["parsed_request"]["question"] = question
    final_response["parsed_request"]["selected_date"] = effective_date
    final_response["parsed_request"]["requested_subjects"] = _display_subject_names(
        candidates, preferences.get("requested_subjects") or []
    )
    final_response["parsed_request"]["requested_markets"] = _market_focus_labels(
        preferences.get("requested_markets") or []
    )
    final_response["headline"] = headline
    final_response["summary"] = structured_response.get("summary") or summary
    final_response["analysis_views"] = dict(analysis_views or {})
    final_response["analysis_brief"] = dict(analysis_brief or {})
    final_response["supporting_evidence"] = dict(supporting_evidence or {})
    final_response["local_only"] = True
    final_response["key_factors"] = list(structured_response.get("key_factors") or [])
    final_response["risks"] = list(structured_response.get("risks") or [])
    final_response["confidence"] = structured_response.get("confidence")
    final_response["recommended_bet_size"] = structured_response.get("recommended_bet_size")
    final_response["risk_level"] = structured_response.get("risk_level")
    final_response["supporting_data"] = list(structured_response.get("supporting_data") or [])
    final_response["clear_summary"] = structured_response.get("clear_summary")
    final_response["deep_analysis"] = list(structured_response.get("deep_analysis") or [])
    final_response["risks_uncertainty"] = list(structured_response.get("risks_uncertainty") or [])
    final_response["recommended_interpretation"] = structured_response.get("recommended_interpretation")
    final_response["final_takeaway"] = structured_response.get("final_takeaway")
    board_payload = dict(final_response)
    board_payload["board"] = _build_board_dictionary(ranked_recommendations)
    final_response["board_contract"] = build_intelligence_board_contract(board_payload)
    persist_started_at = time.perf_counter()
    _intel_trace_timed(
        "persist_before",
        persist_started_at,
        pipeline="run_intelligence_query",
        recommendation_count=len(recommendations),
        parlay_count=len(parlays),
    )
    final_response["evaluation_bundle"] = build_intelligence_evaluation_bundle(
        query={
            "question": question,
            "selected_date": effective_date,
            "sport": preferences.get("sport"),
            "query_type": preferences.get("intent") or preferences.get("query_type"),
        },
        response=final_response,
        persist=True,
    )
    _intel_trace_timed(
        "persist_after",
        persist_started_at,
        pipeline="run_intelligence_query",
        recommendation_count=len(recommendations),
        parlay_count=len(parlays),
    )
    final_response["policy_control"] = dict(final_response.get("evaluation_bundle", {}).get("policy_control") or {})
    final_response["recommendation_history"] = dict(final_response.get("evaluation_bundle", {}).get("history") or {})
    final_response["portfolio_tracking"] = dict(final_response.get("evaluation_bundle", {}).get("portfolio_tracking") or {})
    final_response["portfolio_events"] = dict(final_response.get("evaluation_bundle", {}).get("portfolio_events") or {})
    final_response["portfolio_event_records"] = list(final_response.get("evaluation_bundle", {}).get("portfolio_event_records") or [])
    _attach_intelligence_response_aliases(final_response)
    _intel_trace_timed(
        "response_assembly",
        response_started_at,
        pipeline="run_intelligence_query",
        recommendation_count=len(recommendations),
        parlay_count=len(parlays),
    )
    _intel_trace_timed(
        "request_total",
        request_started_at,
        pipeline="run_intelligence_query",
        recommendation_count=len(recommendations),
        parlay_count=len(parlays),
    )
    return final_response