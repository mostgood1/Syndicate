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
    if preferences.get("analysis_focus") != "basketball_matchups":
        return None
    filtered_candidates = filtered_analysis_candidates(
        candidates,
        sports={"nba", "wnba", "ncaab"},
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
        why_bits = [base_row.get("why")]
        if pace_signal is not None:
            why_bits.append(f"pace {pace_signal:.2f}")
        if usage_signal is not None:
            why_bits.append(f"usage {usage_signal:.2f}")
        if shot_profile_signal is not None:
            why_bits.append(f"shot profile {shot_profile_signal:.2f}")
        table_rows.append(
            {
                **base_row,
                "pace_signal": pace_signal,
                "usage_signal": usage_signal,
                "shot_profile_signal": shot_profile_signal,
                "role_signal": role_signal,
                "why": "; ".join(bit for bit in why_bits if bit),
            }
        )
    if not table_rows:
        return None
    return {
        "focus": "basketball_matchups",
        "title": "Top basketball matchup targets",
        "table": {
            "title": "Top matchup-backed basketball targets",
            "columns": ["rank", "label", "sport", "matchup", "market", "pick", "line", "projected", "live_projection", "odds", "score", "market_fit_score", "pace_signal", "usage_signal", "shot_profile_signal", "role_signal", "why"],
            "rows": table_rows,
        },
        "chart": {
            "title": "Basketball matchup score grid",
            "type": "bar",
            "x_key": "label",
            "series": ["score", "market_fit_score", "pace_signal", "usage_signal", "shot_profile_signal"],
            "rows": table_rows,
        },
    }