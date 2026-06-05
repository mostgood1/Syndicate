from __future__ import annotations

from typing import Any

from syndicate.features.intelligence_analysis_common import candidate_analysis_row
from syndicate.features.intelligence_analysis_common import filtered_analysis_candidates
from syndicate.features.intelligence_analysis_common import first_signal_value


def build_wnba_matchup_analysis_views(
    candidates: list[dict[str, Any]],
    preferences: dict[str, Any],
    *,
    safe_text,
    candidate_market_focuses,
    advanced_signal_text,
) -> dict[str, Any] | None:
    if preferences.get("analysis_focus") != "wnba_matchups":
        return None
    filtered_candidates = filtered_analysis_candidates(
        candidates,
        sports={"wnba"},
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
        team_environment_signal = first_signal_value(candidate, "team_environment_advanced", "team_environment_signal")
        possession_profile_signal = first_signal_value(candidate, "possession_profile_advanced", "possession_profile_signal")
        matchup_pressure_signal = first_signal_value(candidate, "matchup_pressure_advanced", "shot_volume_pressure_advanced")
        rotation_pressure_signal = first_signal_value(candidate, "rotation_pressure_advanced", "minutes_stability_advanced")
        live_shift_signal = first_signal_value(candidate, "live_shift_advanced", "projection_shift_advanced")
        last5_delta_signal = first_signal_value(candidate, "basketball_last5_delta")
        last10_delta_signal = first_signal_value(candidate, "basketball_last10_delta")
        last_game_delta_signal = first_signal_value(candidate, "basketball_last_game_delta")
        workload_delta_signal = first_signal_value(candidate, "basketball_minutes_workload_delta")
        market_key = safe_text((candidate.get("market_fit") or {}).get("market_key"), "").lower()
        analysis_shape = "wnba_role_pressure"
        if market_key in {"rebounds", "blocks", "steals"}:
            analysis_shape = "wnba_possession_pressure"
        elif market_key in {"assists", "pra"}:
            analysis_shape = "wnba_creation_stability"
        why_bits = [base_row.get("why")]
        if team_environment_signal is not None:
            why_bits.append(f"team environment {team_environment_signal:.2f}")
        if possession_profile_signal is not None:
            why_bits.append(f"possession profile {possession_profile_signal:.2f}")
        if matchup_pressure_signal is not None:
            why_bits.append(f"matchup pressure {matchup_pressure_signal:.2f}")
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
                "analysis_shape": analysis_shape,
                "team_environment_signal": team_environment_signal,
                "possession_profile_signal": possession_profile_signal,
                "matchup_pressure_signal": matchup_pressure_signal,
                "rotation_pressure_signal": rotation_pressure_signal,
                "live_shift_signal": live_shift_signal,
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
        "focus": "wnba_matchups",
        "title": "Top WNBA matchup targets",
        "table": {
            "title": "Top WNBA matchup-backed targets",
            "columns": ["rank", "label", "matchup", "market", "pick", "line", "projected", "odds", "score", "market_fit_score", "analysis_shape", "team_environment_signal", "possession_profile_signal", "matchup_pressure_signal", "rotation_pressure_signal", "live_shift_signal", "last5_delta_signal", "last10_delta_signal", "last_game_delta_signal", "workload_delta_signal", "why"],
            "rows": table_rows,
        },
        "chart": {
            "title": "WNBA matchup score grid",
            "type": "bar",
            "x_key": "label",
            "series": ["score", "market_fit_score", "team_environment_signal", "possession_profile_signal", "matchup_pressure_signal", "last5_delta_signal", "last10_delta_signal", "last_game_delta_signal", "workload_delta_signal"],
            "rows": table_rows,
        },
    }