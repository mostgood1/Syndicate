from __future__ import annotations

from typing import Any

from pipeline.intelligence_models import IntelligenceResult

from syndicate.blueprints.ask_the_syndicate_router import RouteDecision


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _result_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return dict(result)
    if isinstance(result, IntelligenceResult):
        return result.to_dict()
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, dict):
            return payload
    return {}


def _result_value(result: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(result, IntelligenceResult) and hasattr(result, field_name):
        value = getattr(result, field_name)
        return default if value is None else value
    payload = _result_payload(result)
    return payload.get(field_name, default)


def _items_to_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        if hasattr(item, "to_dict"):
            items.append(dict(item.to_dict()))
        elif isinstance(item, dict):
            items.append(dict(item))
    return items


def _evidence_to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
        if isinstance(payload, dict):
            return dict(payload)
    if isinstance(value, dict):
        return dict(value)
    return {}


def _to_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except Exception:
        return None


def _to_pct(value: Any) -> float | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    if numeric <= 1.0:
        return round(numeric * 100.0, 2)
    return round(numeric, 2)


def _first_recommendation(result: Any) -> dict[str, Any]:
    recommendations = _items_to_dicts(_result_value(result, "recommendations", ()))
    if recommendations:
        return recommendations[0]
    analysis_views = _mapping_or_empty(_result_value(result, "analysis_views", {}))
    table = _mapping_or_empty(analysis_views.get("table"))
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    if rows:
        first_row = rows[0]
        if isinstance(first_row, dict):
            return dict(first_row)
    return {}


def _analysis_rows(result: Any) -> list[dict[str, Any]]:
    analysis_views = _mapping_or_empty(_result_value(result, "analysis_views", {}))
    table = _mapping_or_empty(analysis_views.get("table"))
    return _items_to_dicts(table.get("rows"))


def _explanation_payload(result: Any) -> dict[str, Any]:
    analysis_brief = _result_value(result, "analysis_brief", None)
    supporting_evidence = _result_value(result, "supporting_evidence", None)
    return {
        "summary": _result_value(result, "summary", None),
        "analysis_brief": _evidence_to_dict(analysis_brief),
        "supporting_evidence": _evidence_to_dict(supporting_evidence),
        "reasoning_steps": _items_to_dicts(_result_value(result, "reasoning_steps", ())),
        "board_notes": list(_result_value(result, "board_notes", ())),
        "readiness_gate": _mapping_or_empty(_result_value(result, "readiness_gate", {})),
    }


def _bet_analysis_schema(result: Any) -> dict[str, Any]:
    top = _first_recommendation(result)
    explanation = _explanation_payload(result)
    selection = top.get("selection") or top.get("pick") or top.get("name") or top.get("label")
    return {
        "schema_type": "bet_analysis",
        "selection": selection,
        "model_probability": _to_pct(top.get("model_probability") or top.get("confidence")),
        "market_probability": _to_pct(top.get("market_probability") or top.get("implied_probability")),
        "edge": _to_float(top.get("adjusted_edge") or top.get("edge") or top.get("price_edge_pct")),
        "EV": _to_float(top.get("expected_value") or top.get("ev_current") or top.get("ev")),
        "confidence": _to_pct(top.get("confidence") or top.get("model_probability")),
        "recommendation": top.get("summary") or top.get("rationale") or top.get("writeup") or top.get("why") or explanation.get("summary"),
        "explanation": {
            "summary": explanation.get("summary"),
            "analysis_brief": explanation.get("analysis_brief", {}),
            "supporting_evidence": explanation.get("supporting_evidence", {}),
            "reasoning_steps": explanation.get("reasoning_steps", []),
            "board_notes": explanation.get("board_notes", []),
            "readiness_gate": explanation.get("readiness_gate", {}),
            "top_candidate": top,
        },
    }


def _teams_from_question(question: str, result: Any) -> list[str]:
    matchup_text = str(_first_recommendation(result).get("matchup") or question or "").strip()
    if " versus " in matchup_text.lower():
        matchup_text = matchup_text.replace("versus", "vs")
    if " vs " in matchup_text.lower():
        parts = matchup_text.split("vs", 1)
        teams = [part.strip(" .,!?") for part in parts if part.strip(" .,!?")]
        if len(teams) >= 2:
            return teams[:2]
    if " at " in matchup_text.lower():
        parts = matchup_text.split(" at ", 1)
        teams = [part.strip(" .,!?") for part in parts if part.strip(" .,!?")]
        if len(teams) >= 2:
            return teams[:2]
    parsed_request = _mapping_or_empty(_result_value(result, "parsed_request", {}))
    requested_subjects = parsed_request.get("requested_subjects") if isinstance(parsed_request.get("requested_subjects"), list) else []
    teams = [str(item).strip() for item in requested_subjects if str(item).strip()]
    return teams[:2]


def _matchup_analysis_schema(question: str, result: Any) -> dict[str, Any]:
    top = _first_recommendation(result)
    rows = _analysis_rows(result)
    explanation = _explanation_payload(result)
    analysis_views = _mapping_or_empty(_result_value(result, "analysis_views", {}))

    key_edges: list[dict[str, Any]] = []
    for row in rows[:3]:
        key_edges.append(
            {
                "selection": row.get("selection") or row.get("pick") or row.get("name") or row.get("label"),
                "model_probability": _to_pct(row.get("model_probability") or row.get("confidence")),
                "market_probability": _to_pct(row.get("market_probability") or row.get("implied_probability")),
                "edge": _to_float(row.get("adjusted_edge") or row.get("edge") or row.get("price_edge_pct")),
                "EV": _to_float(row.get("expected_value") or row.get("ev_current") or row.get("ev")),
                "confidence": _to_pct(row.get("confidence") or row.get("model_probability")),
                "recommendation": row.get("summary") or row.get("rationale") or row.get("why"),
            }
        )

    hidden_factors = [
        {"factor": note}
        for note in explanation.get("board_notes", [])
        if note
    ]
    if analysis_views.get("focus"):
        hidden_factors.append({"factor": f"analysis_focus:{analysis_views.get('focus')}"})

    return {
        "schema_type": "matchup_analysis",
        "teams": _teams_from_question(question, result),
        "win_probability": _to_pct(top.get("model_probability") or top.get("confidence")),
        "key_edges": key_edges,
        "simulation_summary": {
            "summary": explanation.get("summary"),
            "top_candidate": top,
            "analysis_focus": analysis_views.get("focus"),
            "rows_considered": len(rows),
        },
        "hidden_factors": hidden_factors,
        "market_insight": {
            "summary": top.get("market_fit_note") or top.get("summary") or top.get("rationale") or explanation.get("summary"),
            "analysis_views": analysis_views,
            "supporting_evidence": explanation.get("supporting_evidence", {}),
        },
        "explanation": explanation,
    }


def _market_summary_schema(result: Any) -> dict[str, Any]:
    recommendations = _items_to_dicts(_result_value(result, "recommendations", ()))
    top_opportunities: list[dict[str, Any]] = []
    for item in recommendations[:5]:
        top_opportunities.append(
            {
                "selection": item.get("selection") or item.get("pick") or item.get("name") or item.get("label"),
                "market": item.get("market") or item.get("market_label") or item.get("market_key"),
                "model_probability": _to_pct(item.get("model_probability") or item.get("confidence")),
                "market_probability": _to_pct(item.get("market_probability") or item.get("implied_probability")),
                "edge": _to_float(item.get("adjusted_edge") or item.get("edge") or item.get("price_edge_pct")),
                "EV": _to_float(item.get("expected_value") or item.get("ev_current") or item.get("ev")),
                "confidence": _to_pct(item.get("confidence") or item.get("model_probability")),
                "recommendation": item.get("summary") or item.get("rationale") or item.get("writeup") or item.get("why"),
            }
        )

    explanation = _explanation_payload(result)
    return {
        "schema_type": "market_summary",
        "top_opportunities": top_opportunities,
        "rationale_summary": {
            "summary": _result_value(result, "summary", None),
            "analysis_brief": explanation.get("analysis_brief", {}),
            "board_notes": explanation.get("board_notes", []),
            "supporting_evidence": explanation.get("supporting_evidence", {}),
        },
    }


def build_syndicate_query_response(*, question: str, context: dict[str, Any], decision: RouteDecision, result: Any) -> dict[str, Any]:
    query_type = _result_value(result, "query_type", None) or decision.intent or "bet_analysis"
    if decision.intent == "matchup_analysis":
        schema = _matchup_analysis_schema(question, result)
    elif decision.intent == "market_summary":
        schema = _market_summary_schema(result)
    else:
        schema = _bet_analysis_schema(result)

    return {
        "ok": True,
        "surface": "syndicate",
        "question": question,
        "context": dict(context),
        "intent": decision.intent,
        "routing": {
            "handler": decision.handler_name,
            "matched_terms": list(decision.matched_terms),
            "score": decision.score,
        },
        "query_type": query_type,
        "schema_type": schema.get("schema_type", decision.intent),
        "schema": schema,
        "structured_response": schema,
        "engine": {
            "selected_date": _result_value(result, "selected_date", None),
            "query_type": _result_value(result, "query_type", None),
            "preferences": _mapping_or_empty(_result_value(result, "preferences", {})),
            "parsed_request": _mapping_or_empty(_result_value(result, "parsed_request", {})),
            "analysis_views": _mapping_or_empty(_result_value(result, "analysis_views", {})),
            "readiness_gate": _mapping_or_empty(_result_value(result, "readiness_gate", {})),
            "local_only": _result_value(result, "local_only", None),
        },
    }