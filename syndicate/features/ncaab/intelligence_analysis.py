from __future__ import annotations

from typing import Any

from syndicate.features.intelligence_analysis_common import candidate_analysis_row
from syndicate.features.intelligence_analysis_common import filtered_analysis_candidates
from syndicate.features.intelligence_analysis_common import first_signal_value


def build_ncaab_matchup_analysis_views(
    candidates: list[dict[str, Any]],
    preferences: dict[str, Any],
    *,
    safe_text,
    candidate_market_focuses,
    advanced_signal_text,
) -> dict[str, Any] | None:
    if preferences.get("analysis_focus") != "ncaab_matchups":
        return None
    filtered_candidates = filtered_analysis_candidates(
        candidates,
        sports={"ncaab"},
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
        tempo_bucket_signal = first_signal_value(candidate, "tempo_bucket_advanced", "pace_advanced")
        volatility_signal = first_signal_value(candidate, "volatility_advanced", "rotation_volatility_advanced")
        role_signal = first_signal_value(candidate, "minutes_role_advanced", "usage_signal")
        last5_delta_signal = first_signal_value(candidate, "basketball_last5_delta")
        last10_delta_signal = first_signal_value(candidate, "basketball_last10_delta")
        last_game_delta_signal = first_signal_value(candidate, "basketball_last_game_delta")
        workload_delta_signal = first_signal_value(candidate, "basketball_minutes_workload_delta")
        why_bits = [base_row.get("why")]
        if tempo_bucket_signal is not None:
            why_bits.append(f"tempo {tempo_bucket_signal:.2f}")
        if volatility_signal is not None:
            why_bits.append(f"volatility {volatility_signal:.2f}")
        if last5_delta_signal is not None:
            why_bits.append(f"last 5 delta {last5_delta_signal:.2f}")
        if last10_delta_signal is not None:
            why_bits.append(f"last 10 delta {last10_delta_signal:.2f}")
        if last_game_delta_signal is not None:
            why_bits.append(f"last game delta {last_game_delta_signal:.2f}")
        if workload_delta_signal is not None:
            why_bits.append(f"workload delta {workload_delta_signal:.2f}")
        table_rows.append(
            {
                **base_row,
                "analysis_shape": "ncaab_tempo_volatility",
                "tempo_bucket_signal": tempo_bucket_signal,
                "volatility_signal": volatility_signal,
                "role_signal": role_signal,
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
        "focus": "ncaab_matchups",
        "title": "Top NCAAB matchup targets",
        "table": {
            "title": "Top college basketball matchup targets",
            "columns": ["rank", "label", "matchup", "market", "pick", "line", "projected", "odds", "score", "market_fit_score", "analysis_shape", "tempo_bucket_signal", "volatility_signal", "role_signal", "last5_delta_signal", "last10_delta_signal", "last_game_delta_signal", "workload_delta_signal", "why"],
            "rows": table_rows,
        },
        "chart": {
            "title": "NCAAB matchup score grid",
            "type": "bar",
            "x_key": "label",
            "series": ["score", "market_fit_score", "tempo_bucket_signal", "volatility_signal", "last5_delta_signal", "last10_delta_signal", "last_game_delta_signal", "workload_delta_signal"],
            "rows": table_rows,
        },
    }