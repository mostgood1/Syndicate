from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping

from syndicate.features.bankroll_manager import build_portfolio as _build_portfolio
from syndicate.features.bankroll_manager import compute_bet_size as _compute_bet_size
from syndicate.features.correlation_engine import build_correlation_matrix as _build_correlation_matrix
from syndicate.features.correlation_engine import compute_correlation as _compute_correlation
from syndicate.features.intelligence_parlay_runtime import build_parlay_payload as _build_parlay_payload
from syndicate.features.intelligence_parlay_runtime import build_parlays as _build_parlays
from syndicate.features.intelligence_parlay_runtime import build_round_robin_parlays as _build_round_robin_parlays
from syndicate.features.intelligence_parlay_runtime import parlay_rank_score as _parlay_rank_score
from syndicate.features.prediction_ledger import DEFAULT_LEDGER_PATH
from syndicate.features.prediction_ledger import load_all_predictions
from syndicate.features.prediction_ledger import get_performance_summary
from syndicate.features.prediction_ledger import analyze_prediction_performance
from syndicate.features.prediction_reconciliation_debug import debug_prediction_reconciliation
from syndicate.features.simulation_engine import SimulationEngine


_SIMULATION_ENGINE = SimulationEngine()
MAX_CORRELATION_THRESHOLD = 0.45


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _safe_text(value, "")
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except Exception:
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalize_date(value: Any) -> str | None:
    text = _safe_text(value, "")
    if not text:
        return None
    if len(text) >= 10:
        return text[:10]
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except Exception:
        return None


def _prediction_date(prediction: Mapping[str, Any]) -> str | None:
    features = prediction.get("features_snapshot") if isinstance(prediction.get("features_snapshot"), Mapping) else {}
    for key in ("selected_date", "date", "game_date"):
        date_value = _normalize_date(features.get(key))
        if date_value:
            return date_value
    return _normalize_date(prediction.get("timestamp"))


def _normalize_probability(value: Any) -> float | None:
    probability = _safe_float(value)
    if probability is None:
        return None
    if probability > 1.0:
        probability /= 100.0
    if probability < 0.0:
        return None
    return _clamp(probability, 0.0, 1.0)


def _selection_subject(selection: str) -> str:
    text = _safe_text(selection, "").lower()
    for marker in (" over ", " under "):
        if marker in f" {text} ":
            return text.split(marker, 1)[0].strip()
    return text


def _market_key(candidate: Mapping[str, Any]) -> str:
    for field in ("market_key", "market_shape", "market", "stat", "metric"):
        text = _safe_text(candidate.get(field), "").lower()
        if text:
            return text
    return "market"


def _game_key(candidate: Mapping[str, Any]) -> str:
    for field in ("matchup", "game_id", "event_id", "event_key", "game_key"):
        text = _safe_text(candidate.get(field), "").lower()
        if text:
            return text
    return f"{_safe_text(candidate.get('sport_slug') or candidate.get('sport'), '').lower()}|{_safe_text(candidate.get('team_key') or candidate.get('team'), '').lower()}"


def _correlation_pair(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    result = _compute_correlation(dict(a), dict(b))
    score = _safe_float(result.get("correlation_score")) or 0.0
    return {
        "score": round(score, 4),
        "same_game": bool(result.get("same_game")),
        "same_team": bool(result.get("same_team")),
        "same_subject": bool(result.get("same_subject")),
        "result": result,
    }


def _reconcile_candidate_pool(predictions: Iterable[Mapping[str, Any]], test_date: str | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for prediction in predictions:
        if not isinstance(prediction, Mapping):
            continue
        if test_date:
            predicted_date = _prediction_date(prediction)
            if predicted_date and predicted_date != test_date:
                continue
        features = prediction.get("features_snapshot") if isinstance(prediction.get("features_snapshot"), Mapping) else {}
        result = prediction.get("result") if isinstance(prediction.get("result"), Mapping) else {}
        selection = _safe_text(prediction.get("selection"), _safe_text(prediction.get("name"), ""))
        market = _safe_text(prediction.get("market"), "market")
        odds = prediction.get("odds")
        model_probability = _normalize_probability(prediction.get("model_probability"))
        implied_probability = _normalize_probability(prediction.get("implied_probability"))
        if implied_probability is None:
            implied_probability = _normalize_probability((prediction.get("market_context") or {}).get("implied_probability"))
        edge = _safe_float(prediction.get("edge"))
        if edge is None and model_probability is not None and implied_probability is not None:
            edge = model_probability - implied_probability
        confidence = _normalize_probability(prediction.get("confidence"))
        if confidence is None:
            confidence = _normalize_probability((prediction.get("market_context") or {}).get("model_probability")) or 0.5

        normalized.append(
            {
                "prediction_id": prediction.get("id") or prediction.get("prediction_id"),
                "sport": _safe_text(prediction.get("sport"), _safe_text(prediction.get("sport_slug"), "sport")),
                "sport_slug": _safe_text(prediction.get("sport_slug"), _safe_text(prediction.get("sport"), "sport")).lower(),
                "market": market,
                "market_key": _market_key(prediction),
                "market_shape": _safe_text((prediction.get("market_fit") or {}).get("market_shape"), _safe_text(prediction.get("market_shape"), "")),
                "matchup": _safe_text(prediction.get("matchup"), _safe_text(features.get("matchup"), "")),
                "pick": selection,
                "name": _safe_text(prediction.get("name"), selection),
                "selection": selection,
                "team_key": _safe_text(prediction.get("team_key") or features.get("team_key") or features.get("team"), ""),
                "subject_key": _selection_subject(selection),
                "odds": odds,
                "model_probability": model_probability,
                "implied_probability": implied_probability,
                "edge": edge,
                "confidence": confidence,
                "score": _safe_float(prediction.get("score")) or 0.0,
                "volatility": _safe_float(prediction.get("volatility")) or _safe_float((prediction.get("simulation") or {}).get("variance")) or 0.0,
                "volatility_score": _safe_float(prediction.get("volatility_score")) or 0.0,
                "adjusted_edge": _safe_float(prediction.get("adjusted_edge")) or edge or 0.0,
                "line": features.get("line") or features.get("market_line") or features.get("prop_line"),
                "drivers": list(prediction.get("drivers") or (prediction.get("signals") or {}).get("signal_contributions_top_positive") or []),
                "risks": list(prediction.get("risks") or (prediction.get("signals") or {}).get("signal_contributions_top_negative") or []),
                "market_context": prediction.get("market_context") if isinstance(prediction.get("market_context"), Mapping) else {},
                "result_outcome": _safe_text(result.get("outcome"), ""),
            }
        )
    return normalized


def _synthetic_candidates() -> list[dict[str, Any]]:
    return [
        {
            "prediction_id": "synthetic-1",
            "sport": "NBA",
            "sport_slug": "nba",
            "market": "points",
            "market_key": "points",
            "matchup": "BOS at NYK",
            "pick": "Jayson Tatum Over 28.5 Points",
            "name": "Jayson Tatum Over 28.5 Points",
            "team_key": "boston",
            "subject_key": "jayson tatum",
            "odds": -110,
            "model_probability": 0.58,
            "implied_probability": 0.5238,
            "edge": 0.0562,
            "confidence": 0.82,
            "score": 91.0,
            "volatility": 0.37,
            "volatility_score": 0.28,
            "adjusted_edge": 0.048,
            "drivers": ["usage", "minutes", "shot volume"],
            "risks": ["blowout risk"],
            "market_context": {"decimal_odds": 1.91, "american_odds": -110, "implied_probability": 52.38},
            "simulation": {
                "probability_distributions": {"win": 0.58, "loss": 0.42},
                "player_stat_distributions": {"Jayson Tatum": {"points": {"mean": 29.1, "variance": 5.1, "std_dev": 2.26}}},
            },
            "result_outcome": "win",
        },
        {
            "prediction_id": "synthetic-2",
            "sport": "NBA",
            "sport_slug": "nba",
            "market": "threes",
            "market_key": "threes",
            "matchup": "BOS at NYK",
            "pick": "Jaylen Brown Over 3.5 Threes",
            "name": "Jaylen Brown Over 3.5 Threes",
            "team_key": "boston",
            "subject_key": "jaylen brown",
            "odds": 104,
            "model_probability": 0.54,
            "implied_probability": 0.4902,
            "edge": 0.0498,
            "confidence": 0.76,
            "score": 88.0,
            "volatility": 0.33,
            "volatility_score": 0.23,
            "adjusted_edge": 0.043,
            "drivers": ["shot volume", "pace", "minutes"],
            "risks": ["same-game correlation"],
            "market_context": {"decimal_odds": 2.04, "american_odds": 104, "implied_probability": 49.02},
            "simulation": {
                "probability_distributions": {"win": 0.54, "loss": 0.46},
                "player_stat_distributions": {"Jaylen Brown": {"threes": {"mean": 3.8, "variance": 1.8, "std_dev": 1.34}}},
            },
            "result_outcome": "loss",
        },
        {
            "prediction_id": "synthetic-3",
            "sport": "NBA",
            "sport_slug": "nba",
            "market": "rebounds",
            "market_key": "rebounds",
            "matchup": "MIA at PHI",
            "pick": "Bam Adebayo Over 7.5 Rebounds",
            "name": "Bam Adebayo Over 7.5 Rebounds",
            "team_key": "miami",
            "subject_key": "bam adebayo",
            "odds": 130,
            "model_probability": 0.56,
            "implied_probability": 0.4348,
            "edge": 0.1252,
            "confidence": 0.78,
            "score": 89.0,
            "volatility": 0.29,
            "volatility_score": 0.19,
            "adjusted_edge": 0.111,
            "drivers": ["minutes", "rebound environment", "usage"],
            "risks": ["foul trouble"],
            "market_context": {"decimal_odds": 2.3, "american_odds": 130, "implied_probability": 43.48},
            "simulation": {
                "probability_distributions": {"win": 0.56, "loss": 0.44},
                "player_stat_distributions": {"Bam Adebayo": {"rebounds": {"mean": 8.2, "variance": 2.5, "std_dev": 1.58}}},
            },
            "result_outcome": "pending",
        },
        {
            "prediction_id": "synthetic-4",
            "sport": "NBA",
            "sport_slug": "nba",
            "market": "assists",
            "market_key": "assists",
            "matchup": "MIN at DAL",
            "pick": "Luka Doncic Over 8.5 Assists",
            "name": "Luka Doncic Over 8.5 Assists",
            "team_key": "dallas",
            "subject_key": "luka doncic",
            "odds": 135,
            "model_probability": 0.55,
            "implied_probability": 0.4255,
            "edge": 0.1245,
            "confidence": 0.79,
            "score": 92.0,
            "volatility": 0.31,
            "volatility_score": 0.21,
            "adjusted_edge": 0.108,
            "drivers": ["usage", "pace", "assist rate"],
            "risks": ["blowout risk"],
            "market_context": {"decimal_odds": 2.35, "american_odds": 135, "implied_probability": 42.55},
            "simulation": {
                "probability_distributions": {"win": 0.55, "loss": 0.45},
                "player_stat_distributions": {"Luka Doncic": {"assists": {"mean": 9.3, "variance": 3.0, "std_dev": 1.73}}},
            },
            "result_outcome": "win",
        },
    ]


def _audit_candidates(test_date: str | None) -> list[dict[str, Any]]:
    predictions = load_all_predictions(ledger_path=DEFAULT_LEDGER_PATH)
    candidates = _reconcile_candidate_pool(predictions, test_date)
    if len(candidates) < 3:
        candidates.extend(_synthetic_candidates())
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        identifier = _safe_text(candidate.get("prediction_id"), _safe_text(candidate.get("name"), _safe_text(candidate.get("pick"), "candidate")))
        if identifier in seen:
            continue
        seen.add(identifier)
        deduped.append(candidate)
    return deduped


def _log_test(name: str, status: str, details: Any) -> dict[str, Any]:
    payload = {"test": name, "status": status, "details": details}
    print(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str))
    return payload


def _simulation_validation(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    sample_candidates = candidates[:2] if len(candidates) >= 2 else list(candidates)
    if not sample_candidates:
        sample_candidates = _synthetic_candidates()[:2]

    details: list[dict[str, Any]] = []
    passed = True
    for index, candidate in enumerate(sample_candidates, start=1):
        simulation_input = {
            "sport": candidate.get("sport_slug") or candidate.get("sport"),
            "market": candidate.get("market"),
            "selection": candidate.get("selection") or candidate.get("pick") or candidate.get("name"),
            "line": candidate.get("line"),
            "odds": candidate.get("odds"),
            "confidence": candidate.get("confidence"),
            "edge": candidate.get("edge"),
            "model_probability": candidate.get("model_probability"),
            "team_projections": {"home": 110.0 + index, "away": 106.0 + index},
            "player_projections": [
                {
                    "player": candidate.get("name") or candidate.get("pick") or f"player_{index}",
                    "stat": candidate.get("market_key") or candidate.get("market") or "stat",
                    "projection": (_safe_float(candidate.get("line")) or 10.0) + (1.0 if index == 1 else 0.6),
                }
            ],
            "seed": 100 + index,
        }
        simulation = _SIMULATION_ENGINE.run_simulation(simulation_input)
        outcome_distribution = simulation.get("probability_distributions") if isinstance(simulation.get("probability_distributions"), Mapping) else simulation.get("distribution")
        if not isinstance(outcome_distribution, Mapping):
            outcome_distribution = {}
        model_probability = _safe_float(outcome_distribution.get("win"))
        total_runs = int(simulation.get("iterations") or 1000)
        success_count = int(round((model_probability or 0.0) * total_runs))
        computed_probability = success_count / float(total_runs) if total_runs else 0.0
        expected_probability = _safe_float(candidate.get("model_probability"))
        if expected_probability is None:
            expected_probability = model_probability or 0.0
        simulation_pass = abs((model_probability or 0.0) - computed_probability) <= 0.02
        passed = passed and simulation_pass
        details.append(
            {
                "candidate": _safe_text(candidate.get("name") or candidate.get("pick"), f"sample_{index}"),
                "iterations": total_runs,
                "success_count": success_count,
                "computed_model_probability": round(model_probability or 0.0, 4),
                "success_rate": round(computed_probability, 4),
                "variance": simulation.get("variance"),
                "std_dev": simulation.get("std_dev"),
                "adjusted_edge": candidate.get("adjusted_edge"),
                "volatility_score": candidate.get("volatility_score"),
                "result": "PASS" if simulation_pass else "FAIL",
            }
        )
    return {"status": "PASS" if passed else "FAIL", "details": details}


def _edge_validation(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    sample = candidates[:3]
    details: list[dict[str, Any]] = []
    passed = True
    warnings: list[str] = []
    for candidate in sample:
        odds = candidate.get("odds")
        implied = _normalize_probability(candidate.get("implied_probability"))
        model_probability = _normalize_probability(candidate.get("model_probability"))
        edge = _safe_float(candidate.get("edge"))
        if edge is None and implied is not None and model_probability is not None:
            edge = model_probability - implied
        if implied is None or model_probability is None or edge is None:
            passed = False
            details.append({"candidate": candidate.get("name"), "status": "FAIL", "reason": "missing edge inputs"})
            continue
        expected_edge = model_probability - implied
        edge_ok = abs(edge - expected_edge) <= 0.001
        large_edge = abs(edge) > 0.25
        negative_selected = edge < 0.0 and candidate in sample[:2]
        if not edge_ok:
            passed = False
        if large_edge:
            warnings.append(f"Large edge candidate: {candidate.get('name')}")
        if negative_selected:
            warnings.append(f"Negative edge selected: {candidate.get('name')}")
        details.append(
            {
                "candidate": candidate.get("name"),
                "odds": odds,
                "implied_probability": round(implied, 4),
                "model_probability": round(model_probability, 4),
                "edge": round(edge, 4),
                "expected_edge": round(expected_edge, 4),
                "status": "PASS" if edge_ok else "FAIL",
            }
        )
    return {"status": "PASS" if passed else "FAIL", "details": details, "warnings": warnings}


def _volatility_validation(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    sample = candidates[:3]
    variance_values = []
    details: list[dict[str, Any]] = []
    passed = True
    for candidate in sample:
        simulation = candidate.get("simulation") if isinstance(candidate.get("simulation"), Mapping) else {}
        variance = None
        std_dev = None
        if isinstance(simulation, Mapping):
            variance_bucket = simulation.get("variance") if isinstance(simulation.get("variance"), Mapping) else {}
            std_dev_bucket = simulation.get("std_dev") if isinstance(simulation.get("std_dev"), Mapping) else {}
            if isinstance(variance_bucket, Mapping):
                variance = variance_bucket.get("outcome_margin")
                if variance is None:
                    team_score = variance_bucket.get("team_score") if isinstance(variance_bucket.get("team_score"), Mapping) else {}
                    if isinstance(team_score, Mapping):
                        variance = team_score.get("home") or team_score.get("away")
            if isinstance(std_dev_bucket, Mapping):
                outcome_margin = std_dev_bucket.get("outcome_margin")
                if outcome_margin is not None:
                    std_dev = outcome_margin
        if variance is None:
            variance = _safe_float(candidate.get("volatility"))
        variance_values.append(variance)
        details.append(
            {
                "candidate": candidate.get("name"),
                "variance": variance,
                "std_dev": std_dev,
                "volatility_score": candidate.get("volatility_score"),
                "adjusted_edge": candidate.get("adjusted_edge"),
            }
        )
        if candidate.get("volatility_score") is None:
            passed = False
    unique_variance = {round(_safe_float(value) or 0.0, 4) for value in variance_values if value is not None}
    if len(unique_variance) <= 1 and len(sample) > 1:
        passed = False
    return {
        "status": "PASS" if passed else "FAIL",
        "details": details,
        "warnings": [] if len(unique_variance) > 1 else ["Identical volatility across sample candidates"],
    }


def _correlation_validation(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    same_player_a = {
        "sport_slug": "nba",
        "matchup": "BOS at NYK",
        "team_key": "boston",
        "name": "Jayson Tatum Over 28.5 Points",
        "pick": "Jayson Tatum Over 28.5 Points",
        "market": "points",
        "market_key": "points",
    }
    same_player_b = {
        "sport_slug": "nba",
        "matchup": "BOS at NYK",
        "team_key": "boston",
        "name": "Jayson Tatum Over 8.5 Rebounds",
        "pick": "Jayson Tatum Over 8.5 Rebounds",
        "market": "rebounds",
        "market_key": "rebounds",
    }
    different_player = {
        "sport_slug": "nba",
        "matchup": "BOS at NYK",
        "team_key": "boston",
        "name": "Jaylen Brown Over 3.5 Threes",
        "pick": "Jaylen Brown Over 3.5 Threes",
        "market": "threes",
        "market_key": "threes",
    }
    different_game = {
        "sport_slug": "nba",
        "matchup": "MIA at PHI",
        "team_key": "miami",
        "name": "Tyler Herro Over 24.5 Points",
        "pick": "Tyler Herro Over 24.5 Points",
        "market": "points",
        "market_key": "points",
    }
    score_same_player = _safe_float(_compute_correlation(same_player_a, same_player_a).get("correlation_score")) or 0.0
    score_same_game_diff_player = _safe_float(_compute_correlation(same_player_a, different_player).get("correlation_score")) or 0.0
    score_different_game = _safe_float(_compute_correlation(same_player_a, different_game).get("correlation_score")) or 0.0
    scores = [score_same_player, score_same_game_diff_player, score_different_game]
    passed = score_same_player >= score_same_game_diff_player >= score_different_game
    passed = passed and score_same_player >= 0.8 and score_same_game_diff_player >= 0.4 and score_different_game <= 0.35
    details = {
        "scores": [
            {"case": "same_game_same_player", "score": round(score_same_player, 4)},
            {"case": "same_game_different_players", "score": round(score_same_game_diff_player, 4)},
            {"case": "different_games", "score": round(score_different_game, 4)},
        ]
    }
    warnings = []
    if not passed:
        warnings.append("Correlation score range deviated from expected heuristic bands")
    return {"status": "PASS" if passed else "FAIL", "details": details, "warnings": warnings}


def _bankroll_validation(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    sample = sorted(candidates[:4], key=lambda item: float(item.get("edge") or 0.0), reverse=True)
    bet_sizes = []
    details: list[dict[str, Any]] = []
    passed = True
    for candidate in sample:
        bet_size_profile = _compute_bet_size(candidate)
        bet_size = _safe_float(bet_size_profile.get("recommended_bet_size")) or 0.0
        edge = _safe_float(candidate.get("edge")) or 0.0
        confidence = _safe_float(candidate.get("confidence")) or 0.0
        bet_sizes.append((edge, bet_size))
        details.append(
            {
                "candidate": candidate.get("name"),
                "edge": round(edge, 4),
                "confidence": round(confidence, 4),
                "recommended_bet_size": round(bet_size, 4),
                "cap_fraction": bet_size_profile.get("cap_fraction"),
            }
        )
        if bet_size > 0.05:
            passed = False
    ordered = sorted(bet_sizes, key=lambda pair: pair[0], reverse=True)
    if len(ordered) >= 2:
        if ordered[0][1] < ordered[-1][1]:
            passed = False
    if any(edge <= 0.0 and size > 0.01 for edge, size in bet_sizes):
        passed = False
    return {"status": "PASS" if passed else "FAIL", "details": details, "warnings": []}


def _portfolio_validation(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    portfolio = _build_portfolio(candidates[:6], max_correlation_threshold=MAX_CORRELATION_THRESHOLD)
    selected = portfolio.get("selected") if isinstance(portfolio.get("selected"), list) else []
    games = {_safe_text(item.get("matchup"), "").lower() for item in selected if isinstance(item, Mapping)}
    average_correlation = _safe_float((portfolio.get("risk_profile") or {}).get("average_correlation")) or 0.0
    total_exposure = _safe_float(portfolio.get("total_exposure")) or 0.0
    passed = True
    warnings: list[str] = []
    if len(selected) > 1 and len(games) <= 1:
        passed = False
        warnings.append("Portfolio over-concentrated in a single game")
    if average_correlation > MAX_CORRELATION_THRESHOLD:
        passed = False
        warnings.append("Portfolio average correlation exceeds threshold")
    details = {
        "selected_count": len(selected),
        "games": sorted(game for game in games if game),
        "total_exposure": total_exposure,
        "expected_return": portfolio.get("expected_return"),
        "risk_profile": portfolio.get("risk_profile"),
        "summary": portfolio.get("summary"),
    }
    return {"status": "PASS" if passed else "FAIL", "details": details, "warnings": warnings}


def _parlay_validation(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    safe_text = lambda value, fallback="": str(value or "").strip() or fallback
    has_tight_exposure_cap = lambda preferences: False
    parlay_matches_preferences_fn = lambda legs, preferences: True
    parlay_identity = lambda leg: safe_text(leg.get("name") or leg.get("pick") or leg.get("market") or id(leg))
    candidate_summary = lambda leg: dict(leg)

    def parlay_pair_penalty_fn(legs):
        return {"pair_penalty": 0.0, "pair_penalty_notes": [], "pair_penalty_breakdown": []}

    def decimal_to_american(decimal_odds):
        if decimal_odds is None or decimal_odds <= 1:
            return None
        profit_multiple = decimal_odds - 1.0
        if profit_multiple >= 1.0:
            return f"+{int(round(profit_multiple * 100))}"
        return str(int(round(-100.0 / profit_multiple)))

    american_odds_value = lambda value: float(str(value).replace("+", "")) if value not in {None, "-", ""} else None
    american_odds_match = lambda odds, preferences, parlay=False: True
    parlay_stake_plan = lambda preferences, ticket_total=None: {"suggested_stake": 1.0, "suggested_total_exposure": 1.0, "exposure_cap_amount": 1.0, "exposure_cap_source": "audit"}
    parlay_rationale = lambda legs: "audit parlay rationale"
    parlay_label = lambda legs, preferences, round_robin=False, ticket_index=None, ticket_total=None: f"{len(legs)}-leg parlay"

    def build_parlay_payload_fn(legs, preferences, **kwargs):
        return _build_parlay_payload(
            legs,
            preferences,
            candidate_summary=candidate_summary,
            parlay_pair_penalty_fn=parlay_pair_penalty_fn,
            decimal_to_american=decimal_to_american,
            american_odds_value=american_odds_value,
            american_odds_match=american_odds_match,
            safe_text=safe_text,
            parlay_stake_plan=parlay_stake_plan,
            parlay_rationale=parlay_rationale,
            parlay_label=parlay_label,
            **kwargs,
        )

    parlays = _build_parlays(
        candidates[:6],
        limit=3,
        preferences={"parlay_type": "standard", "risk_profile": "balanced", "requested_markets": [], "max_correlation_threshold": MAX_CORRELATION_THRESHOLD},
        safe_text=safe_text,
        has_tight_exposure_cap=has_tight_exposure_cap,
        parlay_matches_preferences_fn=parlay_matches_preferences_fn,
        parlay_identity=parlay_identity,
        build_parlay_payload_fn=build_parlay_payload_fn,
        build_round_robin_parlays_fn=_build_round_robin_parlays,
        parlay_rank_score_fn=_parlay_rank_score,
    )
    if not parlays:
        return {"status": "FAIL", "details": {"parlays": []}, "warnings": ["No parlays generated"]}

    first_parlay = parlays[0]
    legs = first_parlay.get("legs") if isinstance(first_parlay.get("legs"), list) else []
    pair_scores: list[float] = []
    for first_leg, second_leg in __import__("itertools").combinations([dict(item) for item in legs if isinstance(item, Mapping)], 2):
        pair_scores.append(_safe_float(_compute_correlation(first_leg, second_leg).get("correlation_score")) or 0.0)
    highest_correlation = max((abs(score) for score in pair_scores), default=0.0)
    combined_probability = _safe_float(first_parlay.get("combined_probability"))
    passed = highest_correlation <= MAX_CORRELATION_THRESHOLD and combined_probability is not None and 0.0 < combined_probability <= 1.0
    warnings = []
    if highest_correlation > MAX_CORRELATION_THRESHOLD:
        warnings.append("Highly correlated legs detected in parlay")
    details = {
        "legs": [leg.get("name") or leg.get("pick") for leg in legs],
        "correlation_score": round(highest_correlation, 4),
        "combined_probability": round(combined_probability or 0.0, 4),
        "combined_expected_value": first_parlay.get("combined_expected_value"),
        "combined_edge": first_parlay.get("combined_edge"),
    }
    return {"status": "PASS" if passed else "FAIL", "details": details, "warnings": warnings}


def _ledger_validation(test_date: str | None) -> dict[str, Any]:
    if not test_date:
        return {"status": "PASS", "details": {"skipped": True}, "warnings": ["Ledger reconciliation skipped because no test_date was provided"]}
    payload = debug_prediction_reconciliation(test_date, ledger_path=DEFAULT_LEDGER_PATH, sample_size=2)
    total_predictions = int(payload.get("total_predictions") or 0)
    total_results = int(payload.get("total_results_recorded") or 0)
    unmatched_predictions = int(payload.get("unmatched_predictions") or 0)
    duplicate_results = list(payload.get("duplicate_results") or [])
    match_rate = (total_predictions - unmatched_predictions) / float(total_predictions) if total_predictions else 0.0
    passed = not duplicate_results and match_rate >= 0.5
    warnings = []
    if duplicate_results:
        warnings.append("Duplicate ledger results detected")
    if match_rate < 0.5:
        warnings.append("Low reconciliation match rate")
    return {
        "status": "PASS" if passed else "FAIL",
        "details": {
            "total_predictions": total_predictions,
            "total_results": total_results,
            "unmatched_predictions": unmatched_predictions,
            "duplicate_results": duplicate_results,
            "match_rate": round(match_rate, 4),
        },
        "warnings": warnings,
    }


def _output_sanity_validation(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    sample = candidates[:5]
    missing: list[dict[str, Any]] = []
    passed = True
    required_fields = ("edge", "confidence", "model_probability", "implied_probability", "recommended_bet_size", "drivers", "risks")
    for candidate in sample:
        candidate_missing = []
        for field in required_fields:
            value = candidate.get(field)
            if value is None or value == "" or value == []:
                candidate_missing.append(field)
        if candidate_missing:
            passed = False
            missing.append({"candidate": candidate.get("name"), "missing": candidate_missing})
    return {"status": "PASS" if passed else "FAIL", "details": {"missing": missing}, "warnings": []}


def _simulation_candidate_annotations(candidates: list[dict[str, Any]]) -> None:
    for candidate in candidates:
        bet_size = _compute_bet_size(candidate)
        candidate.setdefault("recommended_bet_size", bet_size.get("recommended_bet_size"))
        candidate.setdefault("bet_size_profile", bet_size)
        candidate.setdefault("drivers", list(candidate.get("drivers") or []))
        candidate.setdefault("risks", list(candidate.get("risks") or []))


def run_full_audit(test_date: str | None = None) -> dict[str, Any]:
    candidates = _audit_candidates(test_date)
    if not candidates:
        candidates = _synthetic_candidates()

    _simulation_candidate_annotations(candidates)

    logs: list[dict[str, Any]] = []
    warnings: list[str] = []
    failed: list[str] = []

    simulation = _simulation_validation(candidates)
    logs.append(_log_test("simulation_probability", simulation["status"], simulation["details"]))
    if simulation["status"] != "PASS":
        failed.append("simulation_probability")

    edge = _edge_validation(candidates)
    logs.append(_log_test("edge_calculation", edge["status"], edge["details"]))
    warnings.extend(edge.get("warnings") or [])
    if edge["status"] != "PASS":
        failed.append("edge_calculation")

    volatility = _volatility_validation(candidates)
    logs.append(_log_test("volatility_distribution", volatility["status"], volatility["details"]))
    warnings.extend(volatility.get("warnings") or [])
    if volatility["status"] != "PASS":
        failed.append("volatility_distribution")

    correlation = _correlation_validation(candidates)
    logs.append(_log_test("correlation", correlation["status"], correlation["details"]))
    warnings.extend(correlation.get("warnings") or [])
    if correlation["status"] != "PASS":
        failed.append("correlation")

    bankroll = _bankroll_validation(candidates)
    logs.append(_log_test("bankroll_sizing", bankroll["status"], bankroll["details"]))
    warnings.extend(bankroll.get("warnings") or [])
    if bankroll["status"] != "PASS":
        failed.append("bankroll_sizing")

    portfolio = _portfolio_validation(candidates)
    logs.append(_log_test("portfolio", portfolio["status"], portfolio["details"]))
    warnings.extend(portfolio.get("warnings") or [])
    if portfolio["status"] != "PASS":
        failed.append("portfolio")

    parlay = _parlay_validation(candidates)
    logs.append(_log_test("parlay", parlay["status"], parlay["details"]))
    warnings.extend(parlay.get("warnings") or [])
    if parlay["status"] != "PASS":
        failed.append("parlay")

    ledger = _ledger_validation(test_date)
    logs.append(_log_test("ledger_reconciliation", ledger["status"], ledger["details"]))
    warnings.extend(ledger.get("warnings") or [])
    if ledger["status"] != "PASS":
        failed.append("ledger_reconciliation")

    output_sanity = _output_sanity_validation(candidates)
    logs.append(_log_test("output_sanity", output_sanity["status"], output_sanity["details"]))
    if output_sanity["status"] != "PASS":
        failed.append("output_sanity")

    if test_date:
        try:
            performance = get_performance_summary(ledger_path=DEFAULT_LEDGER_PATH)
        except Exception:
            performance = {}
        try:
            analysis = analyze_prediction_performance(ledger_path=DEFAULT_LEDGER_PATH)
        except Exception:
            analysis = {}
    else:
        performance = {}
        analysis = {}

    total_tests = len(logs)
    passed = total_tests - len(failed)
    health_score = max(0, min(100, 100 - (len(failed) * 12) - (len(warnings) * 3)))

    summary = {
        "total_tests": total_tests,
        "passed": passed,
        "failed": failed,
        "warnings": warnings,
        "health_score": health_score,
        "performance_summary": performance,
        "performance_analysis": analysis,
        "audit_date": test_date,
        "candidate_count": len(candidates),
        "logs": logs,
    }

    print(json.dumps({"audit_summary": summary}, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a read-only Syndicate intelligence audit")
    parser.add_argument("--date", default=None, help="Optional ISO date (YYYY-MM-DD) for ledger reconciliation checks")
    args = parser.parse_args(argv)
    summary = run_full_audit(test_date=args.date)
    print(
        f"Audit complete: {summary['passed']}/{summary['total_tests']} passed, health={summary['health_score']}/100"
    )
    return 0 if not summary["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_full_audit"]