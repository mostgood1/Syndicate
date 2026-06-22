"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Routes intelligence requests to the correct analysis and response builders.

Constraints:
- State-driven execution
- Avoid redundant computation
"""

from __future__ import annotations


def question_requests_explainer(question: str) -> bool:
    lowered = str(question or "").lower()
    return any(token in lowered for token in ("why", "matchup", "matchups", "analysis", "breakdown", "explain"))


def question_requests_performance_analytics(question: str) -> bool:
    lowered = str(question or "").lower()
    return any(
        token in lowered
        for token in (
            "how are we performing",
            "best signals",
            "where losing",
            "where are we losing",
            "performance",
            "roi",
            "win rate",
            "clv",
            "signals",
        )
    )


def analysis_focus_from_question(
    question: str,
    requested_sports: list[str] | tuple[str, ...] | None,
    requested_markets: list[str] | tuple[str, ...] | None,
    *,
    question_targets_mlb_home_runs,
    question_requests_table,
    question_requests_chart,
) -> str | None:
    lowered_question = str(question or "").lower()
    if question_requests_performance_analytics(question):
        return "prediction_performance"
    if question_targets_mlb_home_runs(question):
        return "mlb_home_runs"

    lowered_sports = {str(item).strip().lower() for item in (requested_sports or []) if str(item).strip()}
    lowered_markets = {str(item).strip().lower() for item in (requested_markets or []) if str(item).strip()}
    analysis_requested = question_requests_explainer(question) or question_requests_table(question) or question_requests_chart(question)
    if not analysis_requested:
        return None

    basketball_sports = {"nba", "wnba", "ncaab"}
    football_sports = {"nfl", "ncaaf"}
    hockey_sports = {"nhl"}
    mlb_sports = {"mlb"}
    basketball_markets = {"points", "rebounds", "assists", "threes", "pra", "turnovers", "steals", "blocks"}
    football_markets = {"passing_yards", "rushing_yards", "receiving_yards", "touchdowns"}
    hockey_markets = {"shots", "goals", "assists", "saves"}
    mlb_markets = {"home_runs", "strikeouts", "hits", "total_bases", "rbis", "runs_scored"}

    if len(lowered_sports) > 1:
        if lowered_sports <= football_sports:
            return "football_markets"
        return "market_board"

    if "mlb" in lowered_question and any(
        token in lowered_question
        for token in ("strikeout", "strikeouts", "total base", "total bases", " hits", " rbi", "rbis", "runs scored", "statcast")
    ):
        return "mlb_props"

    if lowered_sports & mlb_sports or lowered_markets & mlb_markets:
        return "mlb_props"

    if "wnba" in lowered_sports:
        return "wnba_matchups"
    if "nba" in lowered_sports:
        return "nba_matchups"
    if "ncaab" in lowered_sports:
        return "ncaab_matchups"
    if lowered_markets & basketball_markets:
        return "nba_matchups"
    if lowered_sports & football_sports or lowered_markets & football_markets:
        return "football_markets"
    if lowered_sports & hockey_sports or lowered_markets & hockey_markets:
        return "hockey_props"
    if lowered_markets or lowered_sports:
        return "market_board"
    return None