from __future__ import annotations

from syndicate.features.mlb.intelligence_analysis import build_mlb_prop_analysis_views
from syndicate.features.nba.intelligence_analysis import build_basketball_matchup_analysis_views
from syndicate.features.ncaab.intelligence_analysis import build_ncaab_matchup_analysis_views
from syndicate.features.nfl.intelligence_analysis import build_football_market_analysis_views
from syndicate.features.nhl.intelligence_analysis import build_hockey_prop_analysis_views
from syndicate.features.wnba.intelligence_analysis import build_wnba_matchup_analysis_views


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
    return (
        build_mlb_home_run_analysis_views(candidates, preferences)
        or build_mlb_prop_analysis_views(
            candidates,
            preferences,
            safe_text=safe_text,
            candidate_market_focuses=candidate_market_focuses,
            advanced_signal_text=advanced_signal_text,
            mlb_statcast_market_text=mlb_statcast_market_text,
        )
        or build_basketball_matchup_analysis_views(
            candidates,
            preferences,
            safe_text=safe_text,
            candidate_market_focuses=candidate_market_focuses,
            advanced_signal_text=advanced_signal_text,
        )
        or build_wnba_matchup_analysis_views(
            candidates,
            preferences,
            safe_text=safe_text,
            candidate_market_focuses=candidate_market_focuses,
            advanced_signal_text=advanced_signal_text,
        )
        or build_ncaab_matchup_analysis_views(
            candidates,
            preferences,
            safe_text=safe_text,
            candidate_market_focuses=candidate_market_focuses,
            advanced_signal_text=advanced_signal_text,
        )
        or build_football_market_analysis_views(
            candidates,
            preferences,
            safe_text=safe_text,
            candidate_market_focuses=candidate_market_focuses,
            advanced_signal_text=advanced_signal_text,
        )
        or build_hockey_prop_analysis_views(
            candidates,
            preferences,
            safe_text=safe_text,
            candidate_market_focuses=candidate_market_focuses,
            advanced_signal_text=advanced_signal_text,
        )
    )