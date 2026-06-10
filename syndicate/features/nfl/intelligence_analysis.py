from __future__ import annotations

from typing import Any

from syndicate.features.intelligence_analysis_common import candidate_analysis_row
from syndicate.features.intelligence_analysis_common import filtered_analysis_candidates
from syndicate.features.intelligence_analysis_common import first_signal_value


def build_football_market_analysis_views(
    candidates: list[dict[str, Any]],
    preferences: dict[str, Any],
    *,
    safe_text,
    candidate_market_focuses,
    advanced_signal_text,
) -> dict[str, Any] | None:
    if preferences.get("analysis_focus") != "football_markets":
        return None
    filtered_candidates = filtered_analysis_candidates(
        candidates,
        sports={"nfl", "ncaaf"},
        preferences=preferences,
        candidate_types={"prop"},
        safe_text=safe_text,
        candidate_market_focuses=candidate_market_focuses,
    )
    base_rows = [
        candidate_analysis_row(candidate, index, safe_text=safe_text, advanced_signal_text=advanced_signal_text)
        for index, candidate in enumerate(filtered_candidates, start=1)
    ]
    table_rows = []
    for base_row, candidate in zip(base_rows, filtered_candidates):
        off_epa_signal = first_signal_value(candidate, "off_epa_advanced", "epa_signal", "epa_off_signal")
        target_share_signal = first_signal_value(candidate, "target_share_advanced", "market_share_advanced")
        pass_rate_signal = first_signal_value(candidate, "pass_rate_advanced", "game_script_advanced")
        air_yards_signal = first_signal_value(candidate, "air_yards_advanced", "downfield_role_advanced")
        why_bits = [base_row.get("why")]
        if off_epa_signal is not None:
            why_bits.append(f"EPA {off_epa_signal:.2f}")
        if target_share_signal is not None:
            why_bits.append(f"target share {target_share_signal:.2f}")
        if pass_rate_signal is not None:
            why_bits.append(f"pass rate {pass_rate_signal:.2f}")
        table_rows.append(
            {
                **base_row,
                "off_epa_signal": off_epa_signal,
                "target_share_signal": target_share_signal,
                "pass_rate_signal": pass_rate_signal,
                "air_yards_signal": air_yards_signal,
                "why": "; ".join(bit for bit in why_bits if bit),
            }
        )
    if not table_rows:
        return None
    return {
        "focus": "football_markets",
        "title": "Top football market targets",
        "table": {
            "title": "Top football market targets",
            "columns": ["rank", "label", "sport", "matchup", "market_label", "pick", "line", "projected", "odds", "expected_value", "edge_pct", "confidence", "model_probability", "market_probability", "historical_context", "reasoning", "score", "market_fit_score", "implied_probability", "off_epa_signal", "target_share_signal", "pass_rate_signal", "air_yards_signal", "why"],
            "rows": table_rows,
        },
        "chart": {
            "title": "Football market score grid",
            "type": "bar",
            "x_key": "label",
            "series": ["score", "market_fit_score", "implied_probability", "off_epa_signal", "target_share_signal", "pass_rate_signal"],
            "rows": table_rows,
        },
    }