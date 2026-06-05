from __future__ import annotations

from typing import Any

from syndicate.features.intelligence_analysis_common import candidate_analysis_row
from syndicate.features.intelligence_analysis_common import filtered_analysis_candidates


def build_hockey_prop_analysis_views(
    candidates: list[dict[str, Any]],
    preferences: dict[str, Any],
    *,
    safe_text,
    candidate_market_focuses,
    advanced_signal_text,
) -> dict[str, Any] | None:
    if preferences.get("analysis_focus") != "hockey_props":
        return None
    filtered_candidates = filtered_analysis_candidates(
        candidates,
        sports={"nhl"},
        preferences=preferences,
        candidate_types={"prop"},
        safe_text=safe_text,
        candidate_market_focuses=candidate_market_focuses,
    )
    table_rows = [
        candidate_analysis_row(candidate, index, safe_text=safe_text, advanced_signal_text=advanced_signal_text)
        for index, candidate in enumerate(filtered_candidates, start=1)
    ]
    if not table_rows:
        return None
    return {
        "focus": "hockey_props",
        "title": "Top hockey prop targets",
        "table": {
            "title": "Top hockey prop targets",
            "columns": ["rank", "label", "matchup", "market_label", "pick", "line", "live_projection", "odds", "score", "market_fit_score", "why"],
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