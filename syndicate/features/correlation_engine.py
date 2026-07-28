from __future__ import annotations

from itertools import combinations
from typing import Any

from syndicate.features.shared.request_path_guard import warn_if_compute_in_request_path


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _normalize_text(value: Any) -> str:
    lowered = _safe_text(value, "").lower()
    lowered = lowered.replace("'", " ").replace("/", " ")
    return " ".join(part for part in lowered.split() if part)


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _safe_text(value, "")
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except Exception:
        return None


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _candidate_game_key(candidate: dict[str, Any]) -> str:
    for field in ("matchup", "game_id", "event_id", "event_key", "game_key"):
        text = _normalize_text(candidate.get(field))
        if text:
            return text
    sport = _normalize_text(candidate.get("sport_slug") or candidate.get("sport"))
    home = _normalize_text(candidate.get("home_team") or candidate.get("team"))
    away = _normalize_text(candidate.get("away_team"))
    if sport and (home or away):
        return " | ".join(part for part in (sport, home, away) if part)
    return ""


def _candidate_team_key(candidate: dict[str, Any]) -> str:
    for field in ("team_key", "team", "team_abbr", "team_slug", "player_team", "home_team", "away_team"):
        text = _normalize_text(candidate.get(field))
        if text:
            return text
    return ""


def _candidate_subject_key(candidate: dict[str, Any]) -> str:
    for field in ("subject_key", "player", "player_name", "name"):
        text = _normalize_text(candidate.get(field))
        if text:
            if field == "name":
                for marker in (" over ", " under "):
                    if marker in f" {text} ":
                        subject = text.split(marker, 1)[0].strip()
                        if subject:
                            return subject
            return text
    pick_text = _normalize_text(candidate.get("pick"))
    if pick_text:
        return pick_text
    return ""


def _candidate_market_key(candidate: dict[str, Any]) -> str:
    for field in ("market_key", "market_shape", "market", "stat", "metric", "prop"):
        text = _normalize_text(candidate.get(field))
        if text:
            return text
    return ""


def _candidate_selection_direction(candidate: dict[str, Any]) -> int:
    selection_text = _normalize_text(" ".join(_safe_text(candidate.get(field), "") for field in ("pick", "name")))
    if " under " in f" {selection_text} ":
        return -1
    if " over " in f" {selection_text} ":
        return 1
    return 0


def _market_script_cluster(candidate: dict[str, Any]) -> str:
    market_text = " ".join(
        _safe_text(candidate.get(field), "")
        for field in ("market", "market_key", "market_shape", "summary", "writeup", "detail", "notes")
    )
    market_text = _normalize_text(market_text)

    cluster_rules = (
        ("pace", ("pace", "tempo", "possession", "possessions", "pace signal", "game script", "fast", "slow")),
        ("scoring", ("points", "scores", "scoring", "runs", "goals", "total", "offense", "offensive", "points per", "score")),
        ("volume", ("rebounds", "assists", "shots", "shot", "hits", "rbi", "turnovers", "saves", "steals", "blocks", "yards", "attempts", "usage")),
        ("defense", ("defense", "defensive", "pressure", "stops", "saves", "blocks", "low scoring")),
    )
    for cluster, tokens in cluster_rules:
        if any(token in market_text for token in tokens):
            return cluster
    return _candidate_market_key(candidate) or "general"


def _same_direction_bonus(first_direction: int, second_direction: int) -> float:
    if first_direction == 0 or second_direction == 0:
        return 0.0
    if first_direction == second_direction:
        return 0.08
    return -0.14


def _script_alignment_bonus(first_cluster: str, second_cluster: str) -> float:
    if not first_cluster or not second_cluster:
        return 0.0
    if first_cluster == second_cluster:
        if first_cluster == "pace":
            return 0.12
        if first_cluster == "scoring":
            return 0.14
        if first_cluster == "volume":
            return 0.10
        if first_cluster == "defense":
            return 0.08
        return 0.06
    cluster_pair = {first_cluster, second_cluster}
    if cluster_pair == {"pace", "scoring"}:
        return 0.07
    if cluster_pair == {"pace", "volume"}:
        return 0.05
    if cluster_pair == {"scoring", "volume"}:
        return 0.06
    if "defense" in cluster_pair and "scoring" in cluster_pair:
        return -0.04
    return 0.0


def _same_game_correlation(candidate_a: dict[str, Any], candidate_b: dict[str, Any]) -> float:
    game_key_a = _candidate_game_key(candidate_a)
    game_key_b = _candidate_game_key(candidate_b)
    if not game_key_a or not game_key_b:
        return 0.0
    if game_key_a != game_key_b:
        return 0.0

    same_team = _candidate_team_key(candidate_a) and _candidate_team_key(candidate_a) == _candidate_team_key(candidate_b)
    same_subject = _candidate_subject_key(candidate_a) and _candidate_subject_key(candidate_a) == _candidate_subject_key(candidate_b)
    same_sport = _normalize_text(candidate_a.get("sport_slug") or candidate_a.get("sport")) == _normalize_text(candidate_b.get("sport_slug") or candidate_b.get("sport"))
    first_direction = _candidate_selection_direction(candidate_a)
    second_direction = _candidate_selection_direction(candidate_b)
    first_cluster = _market_script_cluster(candidate_a)
    second_cluster = _market_script_cluster(candidate_b)

    score = 0.25
    if same_sport:
        score += 0.05
    if same_team:
        score += 0.14
    elif _candidate_team_key(candidate_a) and _candidate_team_key(candidate_b):
        score -= 0.04
    if same_subject:
        score += 0.40
    score += _same_direction_bonus(first_direction, second_direction)
    score += _script_alignment_bonus(first_cluster, second_cluster)

    market_a = _candidate_market_key(candidate_a)
    market_b = _candidate_market_key(candidate_b)
    if market_a and market_b and market_a == market_b:
        score += 0.05

    if same_subject and first_direction != 0 and second_direction != 0 and first_direction != second_direction:
        score -= 0.20

    return score


def _cross_game_correlation(candidate_a: dict[str, Any], candidate_b: dict[str, Any]) -> float:
    same_sport = _normalize_text(candidate_a.get("sport_slug") or candidate_a.get("sport")) == _normalize_text(candidate_b.get("sport_slug") or candidate_b.get("sport"))
    if not same_sport:
        return 0.0

    same_team = _candidate_team_key(candidate_a) and _candidate_team_key(candidate_a) == _candidate_team_key(candidate_b)
    same_subject = _candidate_subject_key(candidate_a) and _candidate_subject_key(candidate_a) == _candidate_subject_key(candidate_b)
    first_cluster = _market_script_cluster(candidate_a)
    second_cluster = _market_script_cluster(candidate_b)
    first_direction = _candidate_selection_direction(candidate_a)
    second_direction = _candidate_selection_direction(candidate_b)

    score = 0.0
    if same_team:
        score += 0.08
    if same_subject:
        score += 0.18
    score += _same_direction_bonus(first_direction, second_direction) * 0.5
    score += _script_alignment_bonus(first_cluster, second_cluster) * 0.6

    market_a = _candidate_market_key(candidate_a)
    market_b = _candidate_market_key(candidate_b)
    if market_a and market_b and market_a == market_b:
        score += 0.04

    return score


def compute_correlation(candidate_a: dict[str, Any], candidate_b: dict[str, Any]) -> dict[str, Any]:
    warn_if_compute_in_request_path("compute_correlation")
    same_game = _candidate_game_key(candidate_a) and _candidate_game_key(candidate_a) == _candidate_game_key(candidate_b)
    same_team = _candidate_team_key(candidate_a) and _candidate_team_key(candidate_a) == _candidate_team_key(candidate_b)
    same_subject = _candidate_subject_key(candidate_a) and _candidate_subject_key(candidate_a) == _candidate_subject_key(candidate_b)
    first_cluster = _market_script_cluster(candidate_a)
    second_cluster = _market_script_cluster(candidate_b)
    first_direction = _candidate_selection_direction(candidate_a)
    second_direction = _candidate_selection_direction(candidate_b)

    if same_game:
        raw_score = _same_game_correlation(candidate_a, candidate_b)
    else:
        raw_score = _cross_game_correlation(candidate_a, candidate_b)

    player_dependency = 0.0
    if same_subject:
        player_dependency = 0.40 if first_direction == second_direction or first_direction == 0 or second_direction == 0 else -0.30
    elif same_team:
        player_dependency = 0.12 if same_game else 0.06
    elif _candidate_team_key(candidate_a) and _candidate_team_key(candidate_b) and _candidate_team_key(candidate_a) != _candidate_team_key(candidate_b):
        player_dependency = -0.06 if same_game else 0.0

    script_dependency = _script_alignment_bonus(first_cluster, second_cluster)
    if same_game and first_direction and second_direction and first_direction != second_direction:
        script_dependency -= 0.08

    correlation_score = _clamp(raw_score + player_dependency + script_dependency)

    return {
        "correlation_score": correlation_score,
        "same_game": bool(same_game),
        "same_team": bool(same_team),
        "same_subject": bool(same_subject),
        "game_key": _candidate_game_key(candidate_a) if same_game else None,
        "script_clusters": [first_cluster, second_cluster],
        "factors": {
            "same_game": round(0.25 if same_game else 0.0, 3),
            "same_team": round(0.14 if same_game and same_team else (0.08 if same_team else 0.0), 3),
            "same_subject": round(0.40 if same_subject else 0.0, 3),
            "player_dependency": round(player_dependency, 3),
            "script_dependency": round(script_dependency, 3),
        },
    }


DEFAULT_BOARD_CORRELATION_BADGE_THRESHOLD = 0.5


def attach_board_correlation_flags(candidates: list[dict[str, Any]], *, threshold: float = DEFAULT_BOARD_CORRELATION_BADGE_THRESHOLD) -> None:
    """Layer 2 Phase 4. Annotates (never removes) candidates whose
    correlation_score with another candidate on the SAME board clears
    `threshold`, so a user sees "5 markets on this game are effectively the
    same bet" instead of 5 unrelated-looking opportunities -- the original
    CLE@CIN screenshot complaint (5 near-identical markets stacked as if
    independent) this phase exists to address.

    Deliberately annotate-only, not suppress: user's explicit call after
    weighing suppress-vs-badge -- board visibility stays complete, the badge
    carries the judgment call instead of hiding it. Threshold is 0.5, looser
    than bankroll_manager.build_portfolio's 0.65 (tuned for bet-SIZING risk,
    a different, higher bar than "is this worth flagging on the board at
    all") -- also the user's explicit call, not a default carried over
    unexamined.

    Mutates each candidate's "correlated_with" list in place (creating an
    empty one on every candidate, even with zero matches, so downstream
    display code can rely on the key's presence rather than a truthiness
    check). Scoped per sport (correlation is never meaningful across sports
    -- every _candidate_*_key lookup is sport-specific-in-practice, e.g. an
    event_id/matchup never collides across two different sports' games) so
    the pairwise pass stays bounded to same-sport candidate counts instead
    of the full multi-sport board.
    """
    warn_if_compute_in_request_path("attach_board_correlation_flags")
    by_sport: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate.setdefault("correlated_with", [])
        sport_key = _normalize_text(candidate.get("sport_slug") or candidate.get("sport"))
        by_sport.setdefault(sport_key, []).append(candidate)

    for group in by_sport.values():
        if len(group) < 2:
            continue
        for candidate_a, candidate_b in combinations(group, 2):
            result = compute_correlation(candidate_a, candidate_b)
            score = _safe_float(result.get("correlation_score")) or 0.0
            if score < threshold:
                continue
            candidate_a["correlated_with"].append(
                {
                    "recommendation_id": candidate_b.get("recommendation_id"),
                    "name": _safe_text(candidate_b.get("selection") or candidate_b.get("name") or candidate_b.get("pick"), "candidate"),
                    "market": candidate_b.get("market"),
                    "correlation_score": round(score, 3),
                    "same_game": bool(result.get("same_game")),
                    "same_subject": bool(result.get("same_subject")),
                }
            )
            candidate_b["correlated_with"].append(
                {
                    "recommendation_id": candidate_a.get("recommendation_id"),
                    "name": _safe_text(candidate_a.get("selection") or candidate_a.get("name") or candidate_a.get("pick"), "candidate"),
                    "market": candidate_a.get("market"),
                    "correlation_score": round(score, 3),
                    "same_game": bool(result.get("same_game")),
                    "same_subject": bool(result.get("same_subject")),
                }
            )


def _candidate_label(candidate: dict[str, Any], index: int) -> str:
    pieces = [
        _safe_text(candidate.get("name"), ""),
        _safe_text(candidate.get("pick"), ""),
        _safe_text(candidate.get("market"), ""),
        _safe_text(candidate.get("sport_slug") or candidate.get("sport"), ""),
    ]
    label = " - ".join(piece for piece in pieces if piece)
    if not label:
        label = f"candidate_{index + 1}"
    return f"{index + 1}. {label}"


def build_correlation_matrix(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    ordered_candidates = list(candidates)
    labels = [_candidate_label(candidate, index) for index, candidate in enumerate(ordered_candidates)]
    matrix: list[list[float]] = []
    pair_details: list[dict[str, Any]] = []

    for row_index, first_candidate in enumerate(ordered_candidates):
        row: list[float] = []
        for col_index, second_candidate in enumerate(ordered_candidates):
            if row_index == col_index:
                row.append(1.0)
                continue
            if col_index < row_index:
                row.append(matrix[col_index][row_index])
                continue
            result = compute_correlation(first_candidate, second_candidate)
            score = float(result["correlation_score"])
            row.append(score)
            pair_details.append(
                {
                    "row": labels[row_index],
                    "col": labels[col_index],
                    "correlation_score": score,
                    "same_game": result["same_game"],
                    "same_team": result["same_team"],
                    "same_subject": result["same_subject"],
                    "factors": result["factors"],
                }
            )
        matrix.append(row)

    return {
        "labels": labels,
        "matrix": matrix,
        "pairs": pair_details,
    }


__all__ = ["compute_correlation", "build_correlation_matrix"]