from __future__ import annotations

import json

from typing import Any

from syndicate.features.intelligence_analysis_common import candidate_analysis_row

from syndicate.features.mlb.intelligence_analysis import build_mlb_prop_analysis_views
from syndicate.features.nba.intelligence_analysis import build_basketball_matchup_analysis_views
from syndicate.features.ncaab.intelligence_analysis import build_ncaab_matchup_analysis_views
from syndicate.features.nfl.intelligence_analysis import build_football_market_analysis_views
from syndicate.features.nhl.intelligence_analysis import build_hockey_prop_analysis_views
from syndicate.features.wnba.intelligence_analysis import build_wnba_matchup_analysis_views


def _intel_trace(event: str, **fields: Any) -> None:
    try:
        print(f"[INTEL_TRACE] {json.dumps({'event': event, **fields}, sort_keys=True, default=str)}", flush=True)
    except Exception:
        print(f"[INTEL_TRACE] {event}", flush=True)


def _analysis_table_sort_options(table: dict[str, Any]) -> list[dict[str, Any]]:
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    columns = {str(column).strip().lower() for column in (table.get("columns") or []) if str(column).strip()}
    row_keys = set()
    for row in rows:
        if isinstance(row, dict):
            row_keys.update(str(key).strip().lower() for key in row.keys() if str(key).strip())
    available = columns | row_keys
    sort_options: list[dict[str, Any]] = []
    for key, label in (
        ("score", "Score"),
        ("expected_value", "Expected value"),
        ("confidence", "Confidence"),
    ):
        if key in available:
            sort_options.append({"key": key, "label": label, "direction": "desc"})
    return sort_options


def _augment_analysis_view_sorting(view: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(view, dict):
        return view
    table = view.get("table") if isinstance(view.get("table"), dict) else None
    if not table:
        return view
    sort_options = _analysis_table_sort_options(table)
    if not sort_options:
        return view
    augmented_table = dict(table)
    augmented_table["sort_options"] = sort_options
    augmented_table["default_sort"] = sort_options[0]
    augmented_view = dict(view)
    augmented_view["table"] = augmented_table
    return augmented_view


def build_generic_market_analysis_views(
    candidates: list[dict[str, Any]],
    preferences: dict[str, Any],
    *,
    safe_text,
    candidate_market_focuses,
    advanced_signal_text,
) -> dict[str, Any] | None:
    if preferences.get("analysis_focus") != "market_board":
        return None

    requested_sports = {str(item).strip().lower() for item in (preferences.get("requested_sports") or []) if str(item).strip()}
    requested_markets = {str(item).strip().lower() for item in (preferences.get("requested_markets") or []) if str(item).strip()}
    filtered = [
        candidate
        for candidate in candidates
        if not requested_sports or safe_text(candidate.get("sport_slug"), "").lower() in requested_sports
    ]
    if requested_markets:
        filtered = [candidate for candidate in filtered if candidate_market_focuses(candidate) & requested_markets]
    _intel_trace(
        "analysis_views_input",
        focus="market_board",
        candidates=len(candidates),
        filtered=len(filtered),
        requested_sports=sorted(requested_sports),
        requested_markets=sorted(requested_markets),
    )
    top_rows = filtered[: min(int(preferences.get("limit") or 5), 10)]
    if not top_rows:
        return None

    table_rows: list[dict[str, Any]] = []
    chart_rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(top_rows, start=1):
        base_row = candidate_analysis_row(candidate, index, safe_text=safe_text, advanced_signal_text=advanced_signal_text)
        market_focuses = sorted(candidate_market_focuses(candidate))
        market_key = next(iter(sorted(requested_markets & set(market_focuses))), None) if requested_markets else None
        if market_key is None:
            market_key = market_focuses[0] if market_focuses else safe_text(candidate.get("market_key"), "")
        row = {
            **base_row,
            "sport_slug": safe_text(candidate.get("sport_slug"), "sport"),
            "candidate_type": safe_text(candidate.get("candidate_type"), "candidate"),
            "market_key": market_key or "general_market",
            "surface": safe_text(candidate.get("surface_title") or candidate.get("surface"), "Board"),
            "advanced_signal_score": round(float(candidate.get("advanced_signal_score") or 0.0), 2),
            "source_summary_score": round(float(candidate.get("source_summary_score") or 0.0), 2),
        }
        table_rows.append(row)
        chart_rows.append(
            {
                "label": row["label"],
                "score": row["score"],
                "market_fit_score": row["market_fit_score"],
                "advanced_signal_score": row["advanced_signal_score"],
                "source_summary_score": row["source_summary_score"],
                "price_edge_pct": row["price_edge_pct"],
                "implied_probability": row["implied_probability"],
            }
        )

    title_bits = []
    if requested_markets:
        title_bits.append(" / ".join(str(item).replace("_", " ").title() for item in sorted(requested_markets)))
    if requested_sports:
        title_bits.append(" / ".join(str(item).upper() for item in sorted(requested_sports)))
    title = "Dynamic market board"
    if title_bits:
        title = f"{' '.join(title_bits)} board"

    return {
        "focus": "market_board",
        "title": title,
        "table": {
            "title": title,
            "columns": ["rank", "label", "sport", "matchup", "market", "market_key", "pick", "line", "projected", "live_projection", "odds", "expected_value", "edge_pct", "confidence", "model_probability", "market_probability", "historical_context", "reasoning", "score", "market_fit_score", "advanced_signal_score", "source_summary_score", "surface", "why"],
            "rows": table_rows,
        },
        "chart": {
            "title": f"{title} score grid",
            "type": "bar",
            "x_key": "label",
            "series": ["score", "market_fit_score", "advanced_signal_score", "source_summary_score", "price_edge_pct", "implied_probability"],
            "rows": chart_rows,
        },
    }


def build_analysis_views(
    candidates: list[dict[str, Any]],
    preferences: dict[str, Any],
    *,
    build_mlb_home_run_analysis_views,
    mlb_statcast_market_text,
    safe_text,
    candidate_market_focuses,
    advanced_signal_text,
) -> dict[str, Any] | None:
    result = (
        _augment_analysis_view_sorting(build_mlb_home_run_analysis_views(candidates, preferences))
        or _augment_analysis_view_sorting(build_mlb_prop_analysis_views(
            candidates,
            preferences,
            safe_text=safe_text,
            candidate_market_focuses=candidate_market_focuses,
            advanced_signal_text=advanced_signal_text,
            mlb_statcast_market_text=mlb_statcast_market_text,
        ))
        or _augment_analysis_view_sorting(build_basketball_matchup_analysis_views(
            candidates,
            preferences,
            safe_text=safe_text,
            candidate_market_focuses=candidate_market_focuses,
            advanced_signal_text=advanced_signal_text,
        ))
        or _augment_analysis_view_sorting(build_wnba_matchup_analysis_views(
            candidates,
            preferences,
            safe_text=safe_text,
            candidate_market_focuses=candidate_market_focuses,
            advanced_signal_text=advanced_signal_text,
        ))
        or _augment_analysis_view_sorting(build_ncaab_matchup_analysis_views(
            candidates,
            preferences,
            safe_text=safe_text,
            candidate_market_focuses=candidate_market_focuses,
            advanced_signal_text=advanced_signal_text,
        ))
        or _augment_analysis_view_sorting(build_football_market_analysis_views(
            candidates,
            preferences,
            safe_text=safe_text,
            candidate_market_focuses=candidate_market_focuses,
            advanced_signal_text=advanced_signal_text,
        ))
        or _augment_analysis_view_sorting(build_hockey_prop_analysis_views(
            candidates,
            preferences,
            safe_text=safe_text,
            candidate_market_focuses=candidate_market_focuses,
            advanced_signal_text=advanced_signal_text,
        ))
        or _augment_analysis_view_sorting(build_generic_market_analysis_views(
            candidates,
            preferences,
            safe_text=safe_text,
            candidate_market_focuses=candidate_market_focuses,
            advanced_signal_text=advanced_signal_text,
        ))
    )
    _intel_trace(
        "analysis_views_output",
        candidates=len(candidates),
        focus=str(preferences.get("analysis_focus") or preferences.get("query_type") or "").strip().lower(),
        has_view=bool(result),
        view_keys=sorted(list(result.keys()))[:8] if isinstance(result, dict) else [],
    )
    return result