from __future__ import annotations

from typing import Any

from syndicate.features.intelligence_analysis_common import candidate_analysis_row
from syndicate.features.intelligence_analysis_common import filtered_analysis_candidates
from syndicate.features.intelligence_analysis_common import first_signal_value


def build_basketball_matchup_analysis_views(
    candidates: list[dict[str, Any]],
    preferences: dict[str, Any],
    *,
    safe_text,
    candidate_market_focuses,
    advanced_signal_text,
) -> dict[str, Any] | None:
    if preferences.get("analysis_focus") != "nba_matchups":
        return None
    filtered_candidates = filtered_analysis_candidates(
        candidates,
        sports={"nba"},
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
        pace_signal = first_signal_value(candidate, "team_pace_signal", "pace_advanced", "pace_signal")
        usage_signal = first_signal_value(candidate, "usage_rate_advanced", "usage_signal", "role_usage_advanced")
        shot_profile_signal = first_signal_value(candidate, "shot_profile_advanced", "shot_quality_advanced")
        role_signal = first_signal_value(candidate, "minutes_role_advanced", "rotation_role_advanced")
        last5_delta_signal = first_signal_value(candidate, "basketball_last5_delta")
        last10_delta_signal = first_signal_value(candidate, "basketball_last10_delta")
        last_game_delta_signal = first_signal_value(candidate, "basketball_last_game_delta")
        workload_delta_signal = first_signal_value(candidate, "basketball_minutes_workload_delta")
        last5_average = first_signal_value(candidate, "basketball_last5_average")
        last10_average = first_signal_value(candidate, "basketball_last10_average")
        last_game_value = first_signal_value(candidate, "basketball_last_game_value")
        projected_minutes = first_signal_value(candidate, "basketball_projected_minutes")
        last10_workload = first_signal_value(candidate, "basketball_last10_workload")
        why_bits = [base_row.get("why")]
        if pace_signal is not None:
            why_bits.append(f"pace {pace_signal:.2f}")
        if usage_signal is not None:
            why_bits.append(f"usage {usage_signal:.2f}")
        if shot_profile_signal is not None:
            why_bits.append(f"shot profile {shot_profile_signal:.2f}")
        if last5_delta_signal is not None:
            why_bits.append(f"last 5 delta {last5_delta_signal:.2f}")
        if last10_delta_signal is not None:
            why_bits.append(f"last 10 delta {last10_delta_signal:.2f}")
        if last_game_delta_signal is not None:
            why_bits.append(f"last game delta {last_game_delta_signal:.2f}")
        if workload_delta_signal is not None:
            why_bits.append(f"workload delta {workload_delta_signal:.2f}")
        market_key = safe_text((candidate.get("market_fit") or {}).get("market_key"), "").lower()
        analysis_shape = "nba_usage_creation"
        if market_key in {"rebounds", "blocks", "steals"}:
            analysis_shape = "nba_rebound_environment"
        elif market_key in {"assists", "pra"}:
            analysis_shape = "nba_playmaking_network"
        table_rows.append(
            {
                **base_row,
                "analysis_shape": analysis_shape,
                "pace_signal": pace_signal,
                "usage_signal": usage_signal,
                "shot_profile_signal": shot_profile_signal,
                "role_signal": role_signal,
                "last5_average": last5_average,
                "last10_average": last10_average,
                "last_game_value": last_game_value,
                "projected_minutes": projected_minutes,
                "last10_workload": last10_workload,
                "last5_delta_signal": last5_delta_signal,
                "last10_delta_signal": last10_delta_signal,
                "last_game_delta_signal": last_game_delta_signal,
                "workload_delta_signal": workload_delta_signal,
                "why": "; ".join(bit for bit in why_bits if bit),
            }
        )
    if not table_rows:
        return None
    return {
        "focus": "nba_matchups",
        "title": "Top NBA matchup targets",
        "table": {
            "title": "Top NBA matchup-backed targets",
            "columns": ["rank", "label", "sport", "matchup", "market", "pick", "line", "projected", "live_projection", "odds", "expected_value", "edge_pct", "confidence", "model_probability", "market_probability", "historical_context", "reasoning", "score", "market_fit_score", "analysis_shape", "pace_signal", "usage_signal", "shot_profile_signal", "role_signal", "last5_delta_signal", "last10_delta_signal", "last_game_delta_signal", "workload_delta_signal", "why"],
            "rows": table_rows,
        },
        "chart": {
            "title": "NBA matchup score grid",
            "type": "bar",
            "x_key": "label",
            "series": ["score", "market_fit_score", "pace_signal", "usage_signal", "shot_profile_signal", "last5_delta_signal", "last10_delta_signal", "last_game_delta_signal", "workload_delta_signal"],
            "rows": table_rows,
        },
    }