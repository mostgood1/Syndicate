from __future__ import annotations

from difflib import SequenceMatcher
from datetime import date
from datetime import timedelta
from functools import lru_cache
from itertools import combinations
from pathlib import Path
import re
import subprocess
from typing import Any

from flask import current_app

from syndicate.blueprints.home import _build_prop_dashboard_row
from syndicate.blueprints.home import _build_sport_overview
from syndicate.blueprints.home import _game_bet_candidates_from_game
from syndicate.features.mlb.sources import daily_artifact_path as mlb_daily_artifact_path
from syndicate.features.mlb.sources import daily_snapshot_oddsapi_pitcher_props_path as mlb_daily_snapshot_oddsapi_pitcher_props_path
from syndicate.features.mlb.sources import daily_top_props_path as mlb_daily_top_props_path
from syndicate.features.mlb.sources import default_mlb_source_root
from syndicate.features.mlb.sources import load_json_file as mlb_load_json_file
from syndicate.features.nba.sources import live_snapshot_path as nba_live_snapshot_path
from syndicate.features.nba.sources import processed_path as nba_processed_path
from syndicate.features.nba.sources import season_betting_card_day_path as nba_season_betting_card_day_path
from syndicate.features.ncaaf import sources as ncaaf_sources
from syndicate.features.ncaab import sources as ncaab_sources
from syndicate.features.nfl import sources as nfl_sources
from syndicate.features.nhl.sources import processed_path as nhl_processed_path
from syndicate.features.nhl.sources import props_lines_snapshot_path as nhl_props_lines_snapshot_path
from syndicate.features.nhl.sources import recommendation_path as nhl_recommendation_path
from syndicate.features.nhl.sources import scoreboard_snapshot_path as nhl_scoreboard_snapshot_path
from syndicate.features.intelligence_analysis_views import build_analysis_views as _runtime_build_analysis_views
from syndicate.features.intelligence_parlay_correlation import parlay_leg_market_key as _runtime_parlay_leg_market_key
from syndicate.features.intelligence_parlay_correlation import parlay_leg_market_shape as _runtime_parlay_leg_market_shape
from syndicate.features.intelligence_parlay_correlation import parlay_matches_preferences as _runtime_parlay_matches_preferences
from syndicate.features.intelligence_parlay_correlation import parlay_pair_penalty as _runtime_parlay_pair_penalty
from syndicate.features.intelligence_parlay_runtime import build_parlay_payload as _runtime_build_parlay_payload
from syndicate.features.intelligence_parlay_runtime import build_parlays as _runtime_build_parlays
from syndicate.features.intelligence_parlay_runtime import build_round_robin_parlays as _runtime_build_round_robin_parlays
from syndicate.features.intelligence_parlay_runtime import parlay_rank_score as _runtime_parlay_rank_score
from syndicate.features.intelligence_router import analysis_focus_from_question as _runtime_analysis_focus_from_question
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.wnba.sources import live_snapshot_path as wnba_live_snapshot_path
from syndicate.features.wnba.sources import processed_path as wnba_processed_path


_SPORT_KEYWORDS: dict[str, set[str]] = {
    "mlb": {"mlb", "baseball", "homer", "home run", "strikeout", "ks", "hits", "total bases", "rbi"},
    "nba": {"nba", "basketball", "points", "rebounds", "assists", "threes", "pra", "double-double"},
    "wnba": {"wnba", "women's basketball", "womens basketball", "threes", "pra", "points", "rebounds", "assists"},
    "nhl": {"nhl", "hockey", "shots", "saves", "goalie", "puck line", "goals", "assists"},
    "nfl": {"nfl", "football", "touchdown", "passing", "rushing", "receiving", "yards"},
    "ncaaf": {"ncaaf", "college football", "cfb", "touchdown", "passing", "rushing", "receiving", "yards"},
    "ncaab": {"ncaab", "college basketball", "cbb", "points", "rebounds", "assists", "threes"},
}

_PROP_MARKET_KEYWORDS = {
    "prop",
    "props",
    "player",
    "pts",
    "reb",
    "ast",
    "pra",
    "threes",
    "shots",
    "strikeout",
    "ks",
    "hits",
    "rbi",
    "yards",
    "touchdown",
}

_GAME_MARKET_KEYWORDS = {"moneyline", "ml", "spread", "side", "total", "game bet", "puck line"}
_DATE_TOKEN_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2}|\d{8})")
_PARLAY_LEG_WORDS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
}
_CONSERVATIVE_RISK_TOKENS = (
    "conservative",
    "safer",
    "safe",
    "safest",
    "low risk",
    "lower risk",
    "high confidence",
    "highest confidence",
    "most likely",
)
_AGGRESSIVE_RISK_TOKENS = ("aggressive", "longshot", "long shot", "high risk", "ceiling", "upside", "highest-upside")
_LOW_CORRELATION_TOKENS = ("low correlation", "uncorrelated", "independent", "diversified")
_MEDIUM_CORRELATION_TOKENS = ("medium correlation", "moderate correlation", "balanced correlation")
_HIGH_CORRELATION_TOKENS = ("high correlation", "correlated", "stacked", "stack", "same game", "same-game", "sgp")
_MARKET_FOCUS_ALIASES: dict[str, tuple[str, ...]] = {
    "home_runs": ("home runs", "home run", "homers", "homer", "hr"),
    "strikeouts": ("strikeouts", "strikeout", "pitcher strikeouts", "ks", "k props"),
    "total_bases": ("total bases", "total base", "batter total bases", "tb"),
    "moneyline": ("moneyline", "ml"),
    "spread": ("spread", "puck line"),
    "total": ("total", "game total", "totals"),
    "points": ("points", "point", "pts"),
    "rebounds": ("rebounds", "rebound", "rebs", "reb"),
    "assists": ("assists", "assist", "asts", "ast"),
    "threes": ("threes", "three pointers", "three pointer", "three point makes", "three point makes", "three point made", "3pm", "3ptm", "3 ptm", "3 point makes", "3 pointers", "3s"),
    "pra": ("pra", "points rebounds assists"),
    "shots": ("shots", "shots on goal", "sog"),
    "saves": ("saves", "save"),
    "goals": ("goals", "goal"),
    "hits": ("hits", "hit"),
    "rbi": ("rbi", "runs batted in"),
    "touchdowns": ("touchdowns", "touchdown", "td"),
    "passing_yards": ("passing yards",),
    "rushing_yards": ("rushing yards",),
    "receiving_yards": ("receiving yards",),
    "turnovers": ("turnovers", "turnover"),
    "steals": ("steals", "steal"),
    "blocks": ("blocks", "block"),
}
_MARKET_FOCUS_LABELS = {
    "home_runs": "Home runs",
    "strikeouts": "Strikeouts",
    "total_bases": "Total bases",
    "moneyline": "Moneyline",
    "spread": "Spread",
    "total": "Total",
    "points": "Points",
    "rebounds": "Rebounds",
    "assists": "Assists",
    "threes": "Threes",
    "pra": "PRA",
    "shots": "Shots",
    "saves": "Saves",
    "goals": "Goals",
    "hits": "Hits",
    "rbi": "RBI",
    "touchdowns": "Touchdowns",
    "passing_yards": "Passing yards",
    "rushing_yards": "Rushing yards",
    "receiving_yards": "Receiving yards",
    "turnovers": "Turnovers",
    "steals": "Steals",
    "blocks": "Blocks",
}
_MARKET_FALLBACK_STOPWORDS = {
    "alt",
    "alternate",
    "batter",
    "bet",
    "bets",
    "game",
    "games",
    "hitter",
    "live",
    "market",
    "markets",
    "pitcher",
    "player",
    "players",
    "pregame",
    "prop",
    "props",
    "team",
}
_BINARY_CEILING_MARKETS = {"home_runs", "touchdowns"}
_VOLUME_PROP_MARKETS = {"strikeouts", "total_bases", "turnovers", "steals", "blocks", "hits", "rbi", "shots", "saves", "goals"}
_COUNTING_PROP_MARKETS = {"points", "rebounds", "assists", "threes", "pra", "passing_yards", "rushing_yards", "receiving_yards"}
_GAME_SIDE_MARKETS = {"moneyline", "spread", "total"}
_SPORT_MARKET_SHAPE_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    ("nba", "points"): {
        "shape_detail": "nba_usage_creation",
        "margin_weight": 4.3,
        "normalized_margin_weight": 12.8,
        "confidence_baseline": 55.5,
        "plus_money_bonus": 1.15,
    },
    ("nba", "assists"): {
        "shape_detail": "nba_playmaking_network",
        "margin_weight": 4.4,
        "normalized_margin_weight": 13.2,
        "confidence_baseline": 55.0,
        "plus_money_bonus": 1.2,
    },
    ("nba", "threes"): {
        "shape_detail": "nba_usage_creation",
        "margin_weight": 4.5,
        "normalized_margin_weight": 13.5,
        "confidence_baseline": 55.0,
        "plus_money_bonus": 1.25,
    },
    ("nba", "pra"): {
        "shape_detail": "nba_usage_creation",
        "margin_weight": 4.2,
        "normalized_margin_weight": 12.6,
        "confidence_baseline": 56.0,
        "plus_money_bonus": 1.1,
    },
    ("nba", "rebounds"): {
        "shape_detail": "nba_rebound_environment",
        "margin_weight": 4.15,
        "normalized_margin_weight": 12.4,
        "confidence_baseline": 55.0,
        "plus_money_bonus": 1.05,
    },
    ("wnba", "points"): {
        "shape_detail": "wnba_role_pressure",
        "margin_weight": 3.75,
        "normalized_margin_weight": 11.4,
        "confidence_baseline": 57.0,
        "plus_money_bonus": 0.9,
    },
    ("wnba", "assists"): {
        "shape_detail": "wnba_creation_stability",
        "margin_weight": 3.85,
        "normalized_margin_weight": 11.8,
        "confidence_baseline": 57.0,
        "plus_money_bonus": 0.95,
    },
    ("wnba", "threes"): {
        "shape_detail": "wnba_creation_stability",
        "margin_weight": 3.7,
        "normalized_margin_weight": 11.2,
        "confidence_baseline": 57.5,
        "plus_money_bonus": 0.85,
    },
    ("wnba", "pra"): {
        "shape_detail": "wnba_role_pressure",
        "margin_weight": 3.65,
        "normalized_margin_weight": 11.0,
        "confidence_baseline": 57.5,
        "plus_money_bonus": 0.85,
    },
    ("wnba", "rebounds"): {
        "shape_detail": "wnba_possession_pressure",
        "margin_weight": 3.95,
        "normalized_margin_weight": 12.1,
        "confidence_baseline": 56.5,
        "plus_money_bonus": 0.95,
    },
    ("ncaab", "points"): {
        "shape_detail": "ncaab_tempo_volatility",
        "margin_weight": 3.7,
        "normalized_margin_weight": 11.3,
        "confidence_baseline": 58.0,
        "plus_money_bonus": 0.8,
    },
    ("ncaab", "assists"): {
        "shape_detail": "ncaab_tempo_volatility",
        "margin_weight": 3.75,
        "normalized_margin_weight": 11.5,
        "confidence_baseline": 58.0,
        "plus_money_bonus": 0.8,
    },
    ("ncaab", "threes"): {
        "shape_detail": "ncaab_tempo_volatility",
        "margin_weight": 3.6,
        "normalized_margin_weight": 11.0,
        "confidence_baseline": 58.5,
        "plus_money_bonus": 0.75,
    },
    ("ncaab", "pra"): {
        "shape_detail": "ncaab_tempo_volatility",
        "margin_weight": 3.55,
        "normalized_margin_weight": 10.8,
        "confidence_baseline": 58.5,
        "plus_money_bonus": 0.7,
    },
    ("ncaab", "rebounds"): {
        "shape_detail": "ncaab_tempo_volatility",
        "margin_weight": 3.8,
        "normalized_margin_weight": 11.7,
        "confidence_baseline": 57.5,
        "plus_money_bonus": 0.85,
    },
}
_MEDIUM_CORRELATION_SHAPE_LIMITS = {
    "binary_ceiling_prop": 1,
    "game_market": 1,
    "counting_prop": 2,
    "volume_prop": 3,
    "general_market": 2,
}
_MEDIUM_CORRELATION_SPORT_SHAPE_LIMITS = {
    ("nba", "volume_prop"): 2,
    ("wnba", "volume_prop"): 2,
    ("ncaab", "volume_prop"): 2,
    ("nhl", "volume_prop"): 2,
}
_MEDIUM_CORRELATION_SPORT_MARKET_LIMITS = {
    ("mlb", "strikeouts"): 2,
    ("mlb", "total_bases"): 1,
}
_MEDIUM_CORRELATION_SPORT_MARKET_PAIR_BLOCKS = {
    ("nba", ("assists", "points")),
    ("wnba", ("assists", "points")),
    ("ncaab", ("assists", "points")),
}
_PARLAY_SPORT_MARKET_PAIR_PENALTIES = {
    ("mlb", ("hits", "total_bases")): 1.0,
    ("mlb", ("hits", "home_runs")): 1.2,
    ("mlb", ("hits", "rbi")): 1.15,
    ("mlb", ("home_runs", "total_bases")): 1.35,
    ("mlb", ("rbi", "total_bases")): 1.2,
    ("mlb", ("home_runs", "rbi")): 1.25,
    ("ncaaf", ("passing_yards", "rushing_yards")): 1.1,
    ("ncaaf", ("passing_yards", "receiving_yards")): 1.25,
    ("ncaaf", ("passing_yards", "touchdowns")): 1.3,
    ("ncaaf", ("receiving_yards", "rushing_yards")): 1.0,
    ("ncaaf", ("receiving_yards", "touchdowns")): 1.2,
    ("ncaaf", ("rushing_yards", "touchdowns")): 1.15,
    ("nfl", ("passing_yards", "rushing_yards")): 1.1,
    ("nfl", ("passing_yards", "receiving_yards")): 1.25,
    ("nfl", ("passing_yards", "touchdowns")): 1.3,
    ("nfl", ("receiving_yards", "rushing_yards")): 1.0,
    ("nfl", ("receiving_yards", "touchdowns")): 1.2,
    ("nfl", ("rushing_yards", "touchdowns")): 1.15,
    ("nhl", ("assists", "goals")): 1.15,
    ("nhl", ("assists", "shots")): 1.1,
    ("nhl", ("goals", "shots")): 1.25,
    ("nba", ("assists", "rebounds")): 1.6,
    ("nba", ("points", "rebounds")): 3.0,
    ("nba", ("points", "threes")): 1.5,
    ("wnba", ("assists", "rebounds")): 1.6,
    ("wnba", ("points", "rebounds")): 3.0,
    ("wnba", ("points", "threes")): 1.5,
    ("ncaab", ("assists", "rebounds")): 1.45,
    ("ncaab", ("points", "rebounds")): 2.5,
    ("ncaab", ("points", "threes")): 1.25,
}
_MARKET_SCRIPT_CLUSTERS = {
    "home_runs": "batter_production",
    "points": "usage",
    "assists": "usage",
    "threes": "usage",
    "turnovers": "usage",
    "passing_yards": "football_production",
    "rushing_yards": "football_production",
    "receiving_yards": "football_production",
    "touchdowns": "football_production",
    "total_bases": "batter_production",
    "hits": "batter_production",
    "rbi": "batter_production",
    "shots": "usage",
    "goals": "usage",
    "rebounds": "possession",
    "blocks": "possession",
    "steals": "possession",
}
_EXPLICIT_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS = {
    ("nba", ("possession", "usage")): 1.02,
    ("nba", ("usage", "usage")): 1.05,
    ("wnba", ("possession", "usage")): 1.02,
    ("wnba", ("usage", "usage")): 1.05,
    ("ncaab", ("possession", "usage")): 1.02,
    ("ncaab", ("usage", "usage")): 1.04,
}
_SCRIPT_CLUSTER_OPPOSING_DIRECTION_MULTIPLIERS = {
    ("mlb", ("batter_production", "batter_production")): 0.45,
    ("ncaaf", ("football_production", "football_production")): 0.45,
    ("nfl", ("football_production", "football_production")): 0.45,
}
_SCRIPT_CLUSTER_PAIR_FALLBACK_PENALTIES = {
    ("ncaaf", ("football_production", "football_production")): 1.0,
    ("nfl", ("football_production", "football_production")): 1.0,
    ("mlb", ("batter_production", "batter_production")): 1.0,
    ("nhl", ("usage", "usage")): 1.1,
    ("nba", ("possession", "possession")): 1.0,
    ("nba", ("usage", "usage")): 1.2,
    ("wnba", ("possession", "possession")): 1.0,
    ("wnba", ("usage", "usage")): 1.2,
    ("ncaab", ("possession", "possession")): 0.9,
    ("ncaab", ("usage", "usage")): 1.1,
}
_LIVE_PARLAY_PAIR_PENALTY_MULTIPLIER = 1.5
_MIXED_TIMING_PARLAY_PAIR_PENALTY_MULTIPLIER = 1.2
_OPPOSING_DIRECTION_PARLAY_PAIR_PENALTY_MULTIPLIER = 0.65
_DIFFERENT_SUBJECT_PARLAY_PAIR_PENALTY_MULTIPLIER = 0.75
_OPPOSING_TEAM_PARLAY_PAIR_PENALTY_MULTIPLIER = 0.75
_SAME_TEAM_SPORT_MARKET_PAIR_PENALTY_MULTIPLIERS = {
    ("nba", ("assists", "rebounds")): 1.05,
    ("nba", ("points", "rebounds")): 1.15,
    ("nba", ("points", "threes")): 1.1,
    ("wnba", ("assists", "rebounds")): 1.05,
    ("wnba", ("points", "rebounds")): 1.15,
    ("wnba", ("points", "threes")): 1.1,
    ("ncaab", ("assists", "rebounds")): 1.05,
    ("ncaab", ("points", "rebounds")): 1.1,
    ("ncaab", ("points", "threes")): 1.05,
}
_SAME_TEAM_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS = {
    ("ncaaf", ("football_production", "football_production")): 1.05,
    ("nfl", ("football_production", "football_production")): 1.05,
    ("nhl", ("usage", "usage")): 1.05,
    ("mlb", ("batter_production", "batter_production")): 1.05,
}
_OPPOSING_TEAM_SPORT_MARKET_PAIR_PENALTY_MULTIPLIERS = {
    ("nba", ("points", "threes")): 0.65,
    ("wnba", ("points", "threes")): 0.65,
    ("ncaab", ("points", "threes")): 0.7,
}
_OPPOSING_TEAM_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS = {
    ("ncaaf", ("football_production", "football_production")): 0.6,
    ("nfl", ("football_production", "football_production")): 0.6,
    ("nhl", ("usage", "usage")): 0.6,
    ("mlb", ("batter_production", "batter_production")): 0.6,
}
_MARKET_DEFAULT_SPORTS: dict[str, tuple[str, ...]] = {
    "home_runs": ("mlb",),
    "strikeouts": ("mlb",),
    "total_bases": ("mlb",),
    "hits": ("mlb",),
    "rbi": ("mlb",),
}
_ADVANCED_SIGNAL_LABELS = {
    "batter_statcast_bb_mult": "Batter Statcast walk multiplier",
    "batter_statcast_hr_mult": "Batter Statcast home-run multiplier",
    "batter_statcast_inplay_mult": "Batter Statcast in-play multiplier",
    "batter_statcast_k_mult": "Batter Statcast strikeout multiplier",
    "basketball_last5_delta": "Basketball last-five delta",
    "basketball_last10_delta": "Basketball last-10 delta",
    "basketball_last_game_delta": "Basketball last-game delta",
    "basketball_minutes_workload_delta": "Basketball minutes-workload delta",
    "pitcher_statcast_bb_mult": "Pitcher Statcast walk multiplier",
    "pitcher_statcast_hr_mult": "Pitcher Statcast home-run multiplier",
    "pitcher_statcast_inplay_mult": "Pitcher Statcast in-play multiplier",
    "pitcher_statcast_k_mult": "Pitcher Statcast strikeout multiplier",
    "bvp_history_source": "BvP history source",
}
_ADVANCED_SIGNAL_TOKENS = (
    "statcast",
    "advanced",
    "barrel",
    "exit_velocity",
    "launch_angle",
    "hard_hit",
    "pitch_mix",
    "xg",
    "epa",
    "pace",
    "share",
)
_TABLE_REQUEST_TOKENS = ("table", "grid", "matrix", "tabular")
_CHART_REQUEST_TOKENS = ("chart", "graph", "plot", "visual")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _effective_date(selected_date: str | None = None) -> str:
    value = str(selected_date or "").strip()
    return value or central_today_iso()


def _safe_text(value: Any, fallback: str = "-") -> str:
    text = str(value or "").strip()
    return text or fallback


def _text_contains_keyword(text: str, keyword: str) -> bool:
    normalized_text = str(text or "").lower()
    normalized_keyword = str(keyword or "").strip().lower()
    if not normalized_text or not normalized_keyword:
        return False
    if re.fullmatch(r"[a-z0-9_+-]+", normalized_keyword):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])", normalized_text))
    return normalized_keyword in normalized_text


def _relative_repo_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(_repo_root()).as_posix()
    except Exception:
        return str(path)


def _safe_int(value: Any) -> int | None:
    try:
        text = str(value or "").strip()
        if not text:
            return None
        return int(float(text))
    except Exception:
        return None


def _numeric_hint(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def _pct_hint(value: Any) -> float | None:
    number = _numeric_hint(value)
    if number is None:
        return None
    if abs(number) <= 1.0:
        number *= 100.0
    return float(number)


def _american_odds_value(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        number = float(match.group(1))
    except Exception:
        return None
    if number == 0:
        return None
    return number


def _american_to_decimal(value: float | None) -> float | None:
    if value is None:
        return None
    if value > 0:
        return 1.0 + (value / 100.0)
    return 1.0 + (100.0 / abs(value))


def _american_implied_probability(value: float | None) -> float | None:
    if value is None:
        return None
    if value > 0:
        return 100.0 / (value + 100.0)
    return abs(value) / (abs(value) + 100.0)


def _decimal_to_american(value: float | None) -> str | None:
    if value is None or value <= 1.0:
        return None
    profit_multiple = float(value) - 1.0
    if profit_multiple >= 1.0:
        american = int(round(profit_multiple * 100.0))
        return f"+{american}"
    american = int(round(-100.0 / profit_multiple))
    return str(american)


def _normalized_market_text(value: Any) -> str:
    lowered = str(value or "").lower()
    lowered = re.sub(r"\b3\s*pt\s*m\b", " 3pm ", lowered)
    lowered = re.sub(r"\b3\s*point\s*makes?\b", " 3pm ", lowered)
    lowered = re.sub(r"\bthree\s+point\s+makes?\b", " 3pm ", lowered)
    normalized = re.sub(r"[^a-z0-9]+", " ", lowered).strip()
    return re.sub(r"\s+", " ", normalized)


def _text_has_market_alias(text: str, alias: str) -> bool:
    normalized_text = _normalized_market_text(text)
    normalized_alias = _normalized_market_text(alias)
    if not normalized_text or not normalized_alias:
        return False
    return f" {normalized_alias} " in f" {normalized_text} "


def _fallback_market_key(text: Any) -> str | None:
    normalized = _normalized_market_text(text)
    if not normalized:
        return None
    tokens = [token for token in normalized.split() if token not in _MARKET_FALLBACK_STOPWORDS]
    if not tokens or len(tokens) > 3:
        return None
    return "_".join(tokens)


def _market_key_from_text(text: Any, *, allow_fallback: bool = False) -> str | None:
    normalized = _normalized_market_text(text)
    if not normalized:
        return None
    for key, aliases in _MARKET_FOCUS_ALIASES.items():
        if any(_text_has_market_alias(normalized, alias) for alias in aliases):
            return key
    if allow_fallback:
        return _fallback_market_key(normalized)
    return None


def _market_label(key: str | None) -> str:
    value = str(key or "").strip().lower()
    if not value:
        return "Market"
    label = _MARKET_FOCUS_LABELS.get(value)
    if label:
        return label
    if value.isupper() and len(value) <= 4:
        return value
    return value.replace("_", " ").title()


def _market_focus_labels(keys: list[str] | tuple[str, ...] | None) -> list[str]:
    labels: list[str] = []
    for key in keys or []:
        label = _market_label(str(key).strip().lower())
        if label:
            labels.append(label)
    return labels


def _market_shape_profile(market_key: str | None, *, candidate_type: str, sport_slug: str | None = None) -> dict[str, Any]:
    key = str(market_key or "").strip().lower()
    sport = str(sport_slug or "").strip().lower()
    if candidate_type == "game" or key in _GAME_SIDE_MARKETS:
        return {
            "shape": "game_market",
            "shape_detail": "game_market",
            "margin_weight": 3.5,
            "normalized_margin_weight": 10.0,
            "edge_weight": 0.7,
            "confidence_weight": 0.06,
            "confidence_baseline": 50.0,
            "margin_cap": 5.0,
            "normalized_margin_cap": 0.35,
            "price_edge_weight": 0.7,
            "plus_money_bonus": 0.0,
        }
    if key in _BINARY_CEILING_MARKETS:
        return {
            "shape": "binary_ceiling_prop",
            "shape_detail": "binary_ceiling_prop",
            "margin_weight": 7.5,
            "normalized_margin_weight": 12.0,
            "edge_weight": 0.85,
            "confidence_weight": 0.05,
            "confidence_baseline": 22.0 if key == "home_runs" else 30.0,
            "margin_cap": 1.5,
            "normalized_margin_cap": 1.0,
            "price_edge_weight": 0.5,
            "plus_money_bonus": 2.0,
        }
    if key in _VOLUME_PROP_MARKETS:
        profile = {
            "shape": "volume_prop",
            "shape_detail": "volume_prop",
            "margin_weight": 5.5,
            "normalized_margin_weight": 16.0,
            "edge_weight": 0.55,
            "confidence_weight": 0.07,
            "confidence_baseline": 54.0,
            "margin_cap": 5.0,
            "normalized_margin_cap": 0.5,
            "price_edge_weight": 0.4,
            "plus_money_bonus": 1.25,
        }
        if sport in {"nba", "wnba", "ncaab"}:
            detail_by_sport = {
                "nba": "nba_rebound_environment",
                "wnba": "wnba_possession_pressure",
                "ncaab": "ncaab_tempo_volatility",
            }
            profile["shape_detail"] = detail_by_sport.get(sport, profile["shape_detail"])
        return profile
    if key in _COUNTING_PROP_MARKETS:
        profile = {
            "shape": "counting_prop",
            "shape_detail": "counting_prop",
            "margin_weight": 4.0,
            "normalized_margin_weight": 12.0,
            "edge_weight": 0.45,
            "confidence_weight": 0.08,
            "confidence_baseline": 55.0,
            "margin_cap": 6.0,
            "normalized_margin_cap": 0.35,
            "price_edge_weight": 0.35,
            "plus_money_bonus": 1.0,
        }
        override = _SPORT_MARKET_SHAPE_OVERRIDES.get((sport, key))
        if override:
            profile.update(override)
        return profile
    return {
        "shape": "general_market",
        "shape_detail": "general_market",
        "margin_weight": 4.5,
        "normalized_margin_weight": 14.0,
        "edge_weight": 0.45,
        "confidence_weight": 0.07,
        "confidence_baseline": 54.0 if candidate_type != "game" else 50.0,
        "margin_cap": 5.0,
        "normalized_margin_cap": 0.4,
        "price_edge_weight": 0.35,
        "plus_money_bonus": 1.0 if candidate_type != "game" else 0.0,
    }


def _market_context(candidate: dict[str, Any]) -> dict[str, Any]:
    american_odds = _american_odds_value(candidate.get("odds"))
    decimal_odds = _american_to_decimal(american_odds)
    implied_probability = _american_implied_probability(american_odds)
    model_probability_pct = _pct_hint(candidate.get("confidence"))
    price_edge_pct = None
    if implied_probability is not None and model_probability_pct is not None:
        price_edge_pct = model_probability_pct - (implied_probability * 100.0)
    return {
        "american_odds": int(american_odds) if american_odds is not None and float(american_odds).is_integer() else american_odds,
        "decimal_odds": round(decimal_odds, 3) if decimal_odds is not None else None,
        "implied_probability": round(implied_probability * 100.0, 2) if implied_probability is not None else None,
        "model_probability": round(model_probability_pct, 2) if model_probability_pct is not None else None,
        "price_edge_pct": round(price_edge_pct, 2) if price_edge_pct is not None else None,
    }


def _market_score_adjustment(market_context: dict[str, Any]) -> float:
    price_edge_pct = market_context.get("price_edge_pct")
    american_odds = market_context.get("american_odds")
    if price_edge_pct is None:
        return 2.0 if american_odds is not None else 0.0
    adjustment = max(-10.0, min(12.0, float(price_edge_pct) * 0.6))
    if american_odds is not None and float(american_odds) >= 100.0 and float(price_edge_pct) > 0.0:
        adjustment += 1.5
    return adjustment


def _humanize_signal_key(key: str) -> str:
    return _ADVANCED_SIGNAL_LABELS.get(key, key.replace("_", " ").strip().title())


def _item_reason_summary(item: dict[str, Any]) -> str:
    for key in ("basketball_reasons", "top_play_reasons", "reasons"):
        values = item.get(key)
        if not isinstance(values, list):
            continue
        fragments = [str(value).strip() for value in values if str(value).strip()]
        if fragments:
            return "; ".join(fragments[:3])
    return ""


def _item_source_summary(item: dict[str, Any]) -> str:
    for value in (
        item.get("writeup"),
        item.get("basketball_summary"),
        item.get("why_explain"),
        item.get("shape_summary"),
        item.get("summary"),
        item.get("detail"),
        _item_reason_summary(item),
    ):
        text = _safe_text(value, "")
        if text:
            return text
    return ""


def _basketball_summary_signals_from_text(item: dict[str, Any]) -> list[dict[str, Any]]:
    summary_text = " ".join(
        part for part in (
            _safe_text(item.get("basketball_summary"), ""),
            _safe_text(item.get("why_explain"), ""),
            _item_reason_summary(item),
        ) if part
    ).lower()
    line_value = _numeric_hint(item.get("line"))
    signals: list[dict[str, Any]] = []
    if not summary_text:
        return signals

    def append_signal(key: str, value: float) -> None:
        signals.append(
            {
                "key": key,
                "label": _humanize_signal_key(key),
                "value": round(float(value), 3),
            }
        )

    if line_value is not None and line_value > 0:
        patterns = (
            (r"last-five average of (?P<value>\d+(?:\.\d+)?)", "basketball_last5_average", "basketball_last5_delta"),
            (r"last-10 sample(?: is [^.,;]*?)? at (?P<value>\d+(?:\.\d+)?)", "basketball_last10_average", "basketball_last10_delta"),
            (r"last game landed at (?P<value>\d+(?:\.\d+)?)", "basketball_last_game_value", "basketball_last_game_delta"),
        )
        for pattern, raw_key, delta_key in patterns:
            match = re.search(pattern, summary_text)
            if not match:
                continue
            value = float(match.group("value"))
            append_signal(raw_key, value)
            append_signal(delta_key, (value - line_value) / max(line_value, 8.0))

    minutes_match = re.search(
        r"projected minutes \((?P<projected>\d+(?:\.\d+)?)\) (?P<relation>sit above|are lighter than) (?:his|her|their) last-10 workload \((?P<workload>\d+(?:\.\d+)?)\)",
        summary_text,
    )
    if minutes_match:
        projected_minutes = float(minutes_match.group("projected"))
        workload_minutes = float(minutes_match.group("workload"))
        relation = 1.0 if minutes_match.group("relation") == "sit above" else -1.0
        append_signal("basketball_projected_minutes", projected_minutes)
        append_signal("basketball_last10_workload", workload_minutes)
        append_signal(
            "basketball_minutes_workload_delta",
            relation * abs(projected_minutes - workload_minutes) / max(workload_minutes, 12.0),
        )
    return signals


def _advanced_signals_from_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for raw_key, raw_value in item.items():
        key = str(raw_key or "").strip().lower()
        if not key:
            continue
        if key == "bvp_history_source":
            value = str(raw_value or "").strip()
            if value:
                signals.append({"key": key, "label": _humanize_signal_key(key), "value": value})
            continue
        numeric_value = _numeric_hint(raw_value)
        if numeric_value is None:
            continue
        if key.endswith("_mult") or any(token in key for token in _ADVANCED_SIGNAL_TOKENS):
            signals.append(
                {
                    "key": key,
                    "label": _humanize_signal_key(key),
                    "value": round(float(numeric_value), 3),
                }
            )
    signals.extend(_basketball_summary_signals_from_text(item))
    return signals


def _market_signal_suffixes(candidate: dict[str, Any]) -> tuple[str, ...]:
    market = " ".join(
        [
            _safe_text(candidate.get("market"), "").lower(),
            _safe_text(candidate.get("pick"), "").lower(),
            _safe_text(candidate.get("name"), "").lower(),
        ]
    )
    if any(token in market for token in ("strikeout", "strike out", " ks", "k ")):
        return ("_k_mult",)
    if any(token in market for token in ("home run", " hr", "hr ")):
        return ("_hr_mult",)
    if any(token in market for token in ("walk", " bb", "bb ")):
        return ("_bb_mult",)
    if any(token in market for token in ("hit", "total bases", "tb", "rbi")):
        return ("_inplay_mult", "_hr_mult")
    return ()


def _relevant_advanced_signals(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    signals = candidate.get("advanced_signals") if isinstance(candidate.get("advanced_signals"), list) else []
    suffixes = _market_signal_suffixes(candidate)
    if not suffixes:
        return [signal for signal in signals if isinstance(signal, dict)]
    matched = [
        signal
        for signal in signals
        if isinstance(signal, dict) and any(str(signal.get("key") or "").endswith(suffix) for suffix in suffixes)
    ]
    return matched or [signal for signal in signals if isinstance(signal, dict)]


def _advanced_signal_delta(signal: dict[str, Any]) -> float | None:
    key = _safe_text(signal.get("key"), "").lower()
    value = signal.get("value")
    if not key or not isinstance(value, (int, float)):
        return None
    numeric_value = float(value)
    if key.startswith("basketball_") and key.endswith("_delta"):
        return numeric_value * 4.0
    if key.endswith("_mult"):
        return (numeric_value - 1.0) / 0.12
    if "target_share" in key or key.endswith("_share") or "share_" in key:
        return (numeric_value - 0.18) / 0.08
    if "barrel_rate" in key:
        return (numeric_value - 0.08) / 0.03
    if "hardhit_rate" in key or "hard_hit_rate" in key:
        return (numeric_value - 0.35) / 0.1
    if "hr_per_bip" in key:
        return (numeric_value - 0.06) / 0.025
    if "xwoba" in key:
        return (numeric_value - 0.32) / 0.04
    if 0.0 <= numeric_value <= 1.0:
        return None
    return (numeric_value - 1.0) / 0.12


def _candidate_advanced_signal_score(candidate: dict[str, Any]) -> float:
    normalized_deltas: list[float] = []
    for signal in _relevant_advanced_signals(candidate):
        if not isinstance(signal, dict):
            continue
        delta = _advanced_signal_delta(signal)
        if delta is not None:
            normalized_deltas.append(delta)
    if not normalized_deltas:
        return 0.0
    direction = -1.0 if "under" in _safe_text(candidate.get("pick"), "").lower() else 1.0
    avg_delta = sum(normalized_deltas) / float(len(normalized_deltas))
    return max(-6.0, min(6.0, avg_delta * 2.5 * direction))


def _basketball_source_summary_score(candidate: dict[str, Any]) -> float:
    if _safe_text(candidate.get("sport_slug"), "").lower() not in {"nba", "wnba", "ncaab"}:
        return 0.0
    if _safe_text(candidate.get("candidate_type"), "").lower() != "prop":
        return 0.0
    text = " ".join(
        part for part in (
            _safe_text(candidate.get("writeup"), ""),
            _safe_text(candidate.get("detail"), ""),
            _safe_text(candidate.get("summary"), ""),
        ) if part
    ).lower()
    if not text:
        return 0.0

    direction = -1.0 if "under" in _safe_text(candidate.get("pick"), "").lower() else 1.0
    adjustments: list[float] = []
    structured_signals = {
        _safe_text(signal.get("key"), ""): float(signal.get("value") or 0.0)
        for signal in (candidate.get("advanced_signals") or [])
        if isinstance(signal, dict)
        and _safe_text(signal.get("key"), "").startswith("basketball_")
        and isinstance(signal.get("value"), (int, float))
    }
    if structured_signals:
        for key in (
            "basketball_last5_delta",
            "basketball_last10_delta",
            "basketball_last_game_delta",
            "basketball_minutes_workload_delta",
        ):
            if key in structured_signals:
                adjustments.append(direction * structured_signals[key] * 8.0)

    if "not just riding a short heater" in text:
        adjustments.append(0.8 * direction)
    if "supports the lower-volume case" in text or "leans under" in text:
        adjustments.append(-0.8 * direction)

    if not adjustments:
        return 0.0
    average_adjustment = sum(adjustments) / float(len(adjustments))
    return max(-3.0, min(3.0, average_adjustment))


def _advanced_signal_text(candidate: dict[str, Any], *, limit: int = 2) -> str:
    fragments: list[str] = []
    for signal in _relevant_advanced_signals(candidate):
        if not isinstance(signal, dict):
            continue
        label = _safe_text(signal.get("label"), "signal")
        value = signal.get("value")
        if isinstance(value, (int, float)):
            fragments.append(f"{label} {float(value):.2f}")
        else:
            text_value = _safe_text(value, "")
            if text_value:
                fragments.append(f"{label} {text_value}")
        if len(fragments) >= limit:
            break
    return "; ".join(fragments)


def _question_targets_mlb_home_runs(question: str) -> bool:
    lowered = str(question or "").lower()
    return any(token in lowered for token in ("home run", "home runs", "homer", "homers", "hr target", "hr targets", "hr matchup", "hr matchups"))


def _question_requests_table(question: str) -> bool:
    lowered = str(question or "").lower()
    return any(token in lowered for token in _TABLE_REQUEST_TOKENS)


def _question_requests_chart(question: str) -> bool:
    lowered = str(question or "").lower()
    return any(token in lowered for token in _CHART_REQUEST_TOKENS)


def _question_requests_explainer(question: str) -> bool:
    lowered = str(question or "").lower()
    return any(token in lowered for token in ("why", "matchup", "matchups", "analysis", "breakdown", "explain"))


def _question_requests_comparison(question: str) -> bool:
    lowered = str(question or "").lower()
    return bool(re.search(r"\b(?:compare|vs\.?|versus)\b", lowered))


def _analysis_focus_from_question(
    question: str,
    requested_sports: list[str] | tuple[str, ...] | None,
    requested_markets: list[str] | tuple[str, ...] | None,
) -> str | None:
    return _runtime_analysis_focus_from_question(
        question,
        requested_sports,
        requested_markets,
        question_targets_mlb_home_runs=_question_targets_mlb_home_runs,
        question_requests_table=_question_requests_table,
        question_requests_chart=_question_requests_chart,
    )


@lru_cache(maxsize=1)
def _mlb_statcast_feature_payload() -> dict[str, Any]:
    path = _mlb_repo_artifact_path("data", "statcast", "features", "player_features_latest.json")
    try:
        payload = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    try:
        import json

        data = json.loads(payload)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _mlb_statcast_profile_from_ids(batter_id: int | None, pitcher_id: int | None) -> dict[str, Any] | None:
    payload = _mlb_statcast_feature_payload()
    if not payload:
        return None
    batters = payload.get("batters") if isinstance(payload.get("batters"), dict) else {}
    pitchers = payload.get("pitchers") if isinstance(payload.get("pitchers"), dict) else {}
    batter = batters.get(str(int(batter_id))) if batter_id is not None and isinstance(batters.get(str(int(batter_id))), dict) else None
    pitcher = pitchers.get(str(int(pitcher_id))) if pitcher_id is not None and isinstance(pitchers.get(str(int(pitcher_id))), dict) else None
    if not batter and not pitcher:
        return None

    batter_overall = batter.get("overall") if isinstance((batter or {}).get("overall"), dict) else {}
    batter_mult = batter.get("mult_overall") if isinstance((batter or {}).get("mult_overall"), dict) else {}
    pitcher_overall = pitcher.get("overall") if isinstance((pitcher or {}).get("overall"), dict) else {}
    pitcher_mult = pitcher.get("mult_overall") if isinstance((pitcher or {}).get("mult_overall"), dict) else {}
    pitcher_mix = pitcher.get("pitch_mix") if isinstance((pitcher or {}).get("pitch_mix"), dict) else {}
    top_pitch_mix = sorted(
        ((str(key), float(value)) for key, value in pitcher_mix.items() if _numeric_hint(value) is not None),
        key=lambda item: item[1],
        reverse=True,
    )[:3]
    return {
        "batter_id": batter_id,
        "pitcher_id": pitcher_id,
        "batter": {
            "ev_mean": _numeric_hint(batter_overall.get("ev_mean")),
            "la_mean": _numeric_hint(batter_overall.get("la_mean")),
            "barrel_rate": _numeric_hint(batter_overall.get("barrel_rate")),
            "hardhit_rate": _numeric_hint(batter_overall.get("hardhit_rate")),
            "hr_per_bip": _numeric_hint(batter_overall.get("hr_per_bip")),
            "xwoba": _numeric_hint(batter_overall.get("xwoba")),
            "pulled_air_rate": _numeric_hint(batter_overall.get("pulled_air_rate")),
            "hr_mult": _numeric_hint(batter_mult.get("hr")),
            "k_mult": _numeric_hint(batter_mult.get("k")),
            "inplay_mult": _numeric_hint(batter_mult.get("inplay")),
        },
        "pitcher": {
            "ev_mean_allowed": _numeric_hint(pitcher_overall.get("ev_mean")),
            "barrel_rate_allowed": _numeric_hint(pitcher_overall.get("barrel_rate")),
            "hardhit_rate_allowed": _numeric_hint(pitcher_overall.get("hardhit_rate")),
            "hr_per_bip_allowed": _numeric_hint(pitcher_overall.get("hr_per_bip")),
            "xwoba_allowed": _numeric_hint(pitcher_overall.get("xwoba")),
            "hr_mult": _numeric_hint(pitcher_mult.get("hr")),
            "k_mult": _numeric_hint(pitcher_mult.get("k")),
            "inplay_mult": _numeric_hint(pitcher_mult.get("inplay")),
            "top_pitch_mix": [
                {"pitch_type": pitch_type, "share": round(share, 3)}
                for pitch_type, share in top_pitch_mix
            ],
        },
        "generated_at": ((payload.get("meta") or {}).get("generated_at") if isinstance(payload.get("meta"), dict) else None),
    }


def _candidate_mlb_statcast_profile(candidate: dict[str, Any]) -> dict[str, Any] | None:
    if _safe_text(candidate.get("sport_slug"), "").lower() != "mlb":
        return None
    batter_id = _safe_int(candidate.get("batter_id"))
    pitcher_id = _safe_int(candidate.get("opponent_pitcher_id") or candidate.get("pitcher_id"))
    return _mlb_statcast_profile_from_ids(batter_id, pitcher_id)


def _mlb_statcast_profile_text(profile: dict[str, Any] | None) -> str:
    if not isinstance(profile, dict):
        return ""
    batter = profile.get("batter") if isinstance(profile.get("batter"), dict) else {}
    pitcher = profile.get("pitcher") if isinstance(profile.get("pitcher"), dict) else {}
    fragments: list[str] = []
    barrel_rate = batter.get("barrel_rate")
    ev_mean = batter.get("ev_mean")
    hr_per_bip = batter.get("hr_per_bip")
    pitcher_hr_per_bip = pitcher.get("hr_per_bip_allowed")
    if barrel_rate is not None:
        fragments.append(f"barrel {float(barrel_rate) * 100.0:.1f}%")
    if ev_mean is not None:
        fragments.append(f"EV {float(ev_mean):.1f}")
    if hr_per_bip is not None:
        fragments.append(f"batter HR/BIP {float(hr_per_bip) * 100.0:.1f}%")
    if pitcher_hr_per_bip is not None:
        fragments.append(f"pitcher HR/BIP allowed {float(pitcher_hr_per_bip) * 100.0:.1f}%")
    return "; ".join(fragments[:4])


def _mlb_statcast_market_text(profile: dict[str, Any] | None, market_key: str) -> str:
    if not isinstance(profile, dict):
        return ""
    batter = profile.get("batter") if isinstance(profile.get("batter"), dict) else {}
    pitcher = profile.get("pitcher") if isinstance(profile.get("pitcher"), dict) else {}
    normalized_market = _safe_text(market_key, "general_market").lower()
    fragments: list[str] = []
    if normalized_market == "strikeouts":
        if pitcher.get("k_mult") is not None:
            fragments.append(f"pitcher K mult {float(pitcher.get('k_mult')):.2f}")
        if batter.get("k_mult") is not None:
            fragments.append(f"batter K mult {float(batter.get('k_mult')):.2f}")
        pitch_mix = pitcher.get("top_pitch_mix") if isinstance(pitcher.get("top_pitch_mix"), list) else []
        if pitch_mix:
            fragments.append(
                "pitch mix " + ", ".join(
                    f"{_safe_text(item.get('pitch_type'), '?')} {float(item.get('share') or 0.0) * 100.0:.0f}%"
                    for item in pitch_mix[:3]
                    if isinstance(item, dict)
                )
            )
        if pitcher.get("xwoba_allowed") is not None:
            fragments.append(f"pitcher xwOBA allowed {float(pitcher.get('xwoba_allowed')):.3f}")
        return "; ".join(fragments[:4])
    if normalized_market in {"total_bases", "hits", "rbis", "runs_scored"}:
        if batter.get("xwoba") is not None:
            fragments.append(f"batter xwOBA {float(batter.get('xwoba')):.3f}")
        if batter.get("ev_mean") is not None:
            fragments.append(f"EV {float(batter.get('ev_mean')):.1f}")
        if batter.get("hardhit_rate") is not None:
            fragments.append(f"hard-hit {float(batter.get('hardhit_rate')) * 100.0:.1f}%")
        if batter.get("inplay_mult") is not None:
            fragments.append(f"in-play mult {float(batter.get('inplay_mult')):.2f}")
        if pitcher.get("xwoba_allowed") is not None:
            fragments.append(f"pitcher xwOBA allowed {float(pitcher.get('xwoba_allowed')):.3f}")
        return "; ".join(fragments[:5])
    return _mlb_statcast_profile_text(profile)


def _mlb_home_run_analysis_views(candidates: list[dict[str, Any]], preferences: dict[str, Any]) -> dict[str, Any] | None:
    if preferences.get("analysis_focus") != "mlb_home_runs":
        return None
    hr_candidates = [
        candidate
        for candidate in candidates
        if _safe_text(candidate.get("sport_slug"), "").lower() == "mlb"
        and any(
            token in " ".join([_safe_text(candidate.get("market"), "").lower(), _safe_text(candidate.get("name"), "").lower()])
            for token in ("home run", " hr", "hr ")
        )
    ]
    if not hr_candidates:
        return None

    def _signal_value(candidate: dict[str, Any], key: str) -> float | None:
        for signal in candidate.get("advanced_signals") or []:
            if isinstance(signal, dict) and _safe_text(signal.get("key"), "") == key:
                value = signal.get("value")
                if isinstance(value, (int, float)):
                    return round(float(value), 3)
        return None

    top_rows = hr_candidates[: min(int(preferences.get("limit") or 5), 10)]
    table_rows: list[dict[str, Any]] = []
    chart_rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(top_rows, start=1):
        batter_hr_mult = _signal_value(candidate, "batter_statcast_hr_mult")
        pitcher_hr_mult = _signal_value(candidate, "pitcher_statcast_hr_mult")
        statcast_profile = candidate.get("mlb_statcast_profile") if isinstance(candidate.get("mlb_statcast_profile"), dict) else {}
        batter_profile = statcast_profile.get("batter") if isinstance(statcast_profile.get("batter"), dict) else {}
        pitcher_profile = statcast_profile.get("pitcher") if isinstance(statcast_profile.get("pitcher"), dict) else {}
        table_rows.append(
            {
                "rank": index,
                "player": _safe_text(candidate.get("name"), "Play"),
                "matchup": _safe_text(candidate.get("matchup"), "-"),
                "pick": _safe_text(candidate.get("pick"), "-"),
                "odds": _safe_text(candidate.get("odds"), "-"),
                "confidence": _safe_text(candidate.get("confidence"), "-"),
                "edge": _safe_text(candidate.get("edge"), "-"),
                "score": round(float(candidate.get("score") or 0.0), 2),
                "advanced_signal_score": round(float(candidate.get("advanced_signal_score") or 0.0), 2),
                "batter_hr_mult": batter_hr_mult,
                "pitcher_hr_mult": pitcher_hr_mult,
                "barrel_rate": round(float(batter_profile.get("barrel_rate") or 0.0) * 100.0, 1) if batter_profile.get("barrel_rate") is not None else None,
                "ev_mean": round(float(batter_profile.get("ev_mean") or 0.0), 1) if batter_profile.get("ev_mean") is not None else None,
                "batter_hr_per_bip": round(float(batter_profile.get("hr_per_bip") or 0.0) * 100.0, 1) if batter_profile.get("hr_per_bip") is not None else None,
                "pitcher_hr_per_bip_allowed": round(float(pitcher_profile.get("hr_per_bip_allowed") or 0.0) * 100.0, 1) if pitcher_profile.get("hr_per_bip_allowed") is not None else None,
                "why": _mlb_statcast_profile_text(statcast_profile) or _advanced_signal_text(candidate, limit=3) or _safe_text(candidate.get("writeup"), "-"),
            }
        )
        chart_rows.append(
            {
                "label": _safe_text(candidate.get("name"), "Play"),
                "score": round(float(candidate.get("score") or 0.0), 2),
                "advanced_signal_score": round(float(candidate.get("advanced_signal_score") or 0.0), 2),
                "confidence": _pct_hint(candidate.get("confidence")),
                "batter_hr_mult": batter_hr_mult,
                "pitcher_hr_mult": pitcher_hr_mult,
                "barrel_rate": round(float(batter_profile.get("barrel_rate") or 0.0) * 100.0, 1) if batter_profile.get("barrel_rate") is not None else None,
                "ev_mean": round(float(batter_profile.get("ev_mean") or 0.0), 1) if batter_profile.get("ev_mean") is not None else None,
            }
        )

    return {
        "focus": "mlb_home_runs",
        "title": "Top MLB home run targets",
        "table": {
            "title": "Top 10 likely HR targets",
            "columns": [
                "rank",
                "player",
                "matchup",
                "pick",
                "odds",
                "confidence",
                "edge",
                "score",
                "advanced_signal_score",
                "batter_hr_mult",
                "pitcher_hr_mult",
                "barrel_rate",
                "ev_mean",
                "batter_hr_per_bip",
                "pitcher_hr_per_bip_allowed",
                "why",
            ],
            "rows": table_rows,
        },
        "chart": {
            "title": "HR target score grid",
            "type": "bar",
            "x_key": "label",
            "series": ["score", "advanced_signal_score", "confidence", "batter_hr_mult", "pitcher_hr_mult", "barrel_rate", "ev_mean"],
            "rows": chart_rows,
        },
    }


def _candidate_analysis_row(candidate: dict[str, Any], index: int) -> dict[str, Any]:
    market_context = candidate.get("market_context") if isinstance(candidate.get("market_context"), dict) else {}
    market_fit = candidate.get("market_fit") if isinstance(candidate.get("market_fit"), dict) else {}
    why = (
        _safe_text(market_fit.get("market_fit_note"), "")
        or _advanced_signal_text(candidate, limit=3)
        or _safe_text(candidate.get("writeup"), "")
        or _safe_text(candidate.get("detail"), "")
        or _safe_text(candidate.get("summary"), "")
    )
    return {
        "rank": index,
        "label": _safe_text(candidate.get("name"), "Play"),
        "sport": _safe_text(candidate.get("sport"), "Sport"),
        "matchup": _safe_text(candidate.get("matchup"), "-"),
        "market": _safe_text(candidate.get("market"), "Market"),
        "market_label": _safe_text(market_fit.get("market_label"), "Market"),
        "market_shape": _safe_text(market_fit.get("market_shape"), "general_market"),
        "pick": _safe_text(candidate.get("pick"), "-"),
        "line": _safe_text(candidate.get("line"), "-"),
        "projected": _safe_text(candidate.get("projected"), "-"),
        "live_projection": _safe_text(candidate.get("live_projection"), "-"),
        "actual": _safe_text(candidate.get("actual"), "-"),
        "odds": _safe_text(candidate.get("odds"), "-"),
        "confidence": _safe_text(candidate.get("confidence"), "-"),
        "edge": _safe_text(candidate.get("edge"), "-"),
        "score": round(float(candidate.get("score") or 0.0), 2),
        "market_fit_score": round(float(market_fit.get("market_fit_score") or 0.0), 2),
        "price_edge_pct": market_context.get("price_edge_pct"),
        "implied_probability": market_context.get("implied_probability"),
        "why": why or "Local board and model context support this angle.",
    }


def _analysis_candidate_rows(
    candidates: list[dict[str, Any]],
    *,
    sports: set[str],
    preferences: dict[str, Any],
) -> list[dict[str, Any]]:
    requested_markets = {str(item).strip().lower() for item in (preferences.get("requested_markets") or []) if str(item).strip()}
    filtered = [candidate for candidate in candidates if _safe_text(candidate.get("sport_slug"), "").lower() in sports]
    if requested_markets:
        filtered = [candidate for candidate in filtered if _candidate_market_focuses(candidate) & requested_markets]
    top_rows = filtered[: min(int(preferences.get("limit") or 5), 10)]
    return [_candidate_analysis_row(candidate, index) for index, candidate in enumerate(top_rows, start=1)]


def _basketball_matchup_analysis_views(candidates: list[dict[str, Any]], preferences: dict[str, Any]) -> dict[str, Any] | None:
    if preferences.get("analysis_focus") != "basketball_matchups":
        return None
    table_rows = _analysis_candidate_rows(candidates, sports={"nba", "wnba", "ncaab"}, preferences=preferences)
    if not table_rows:
        return None
    return {
        "focus": "basketball_matchups",
        "title": "Top basketball matchup targets",
        "table": {
            "title": "Top matchup-backed basketball targets",
            "columns": ["rank", "label", "sport", "matchup", "market", "pick", "line", "projected", "live_projection", "odds", "score", "market_fit_score", "why"],
            "rows": table_rows,
        },
        "chart": {
            "title": "Basketball matchup score grid",
            "type": "bar",
            "x_key": "label",
            "series": ["score", "market_fit_score", "price_edge_pct"],
            "rows": table_rows,
        },
    }


def _football_market_analysis_views(candidates: list[dict[str, Any]], preferences: dict[str, Any]) -> dict[str, Any] | None:
    if preferences.get("analysis_focus") != "football_markets":
        return None
    table_rows = _analysis_candidate_rows(candidates, sports={"nfl", "ncaaf"}, preferences=preferences)
    if not table_rows:
        return None
    return {
        "focus": "football_markets",
        "title": "Top football market targets",
        "table": {
            "title": "Top football market targets",
            "columns": ["rank", "label", "sport", "matchup", "market_label", "pick", "line", "projected", "odds", "score", "market_fit_score", "implied_probability", "why"],
            "rows": table_rows,
        },
        "chart": {
            "title": "Football market score grid",
            "type": "bar",
            "x_key": "label",
            "series": ["score", "market_fit_score", "implied_probability"],
            "rows": table_rows,
        },
    }


def _hockey_prop_analysis_views(candidates: list[dict[str, Any]], preferences: dict[str, Any]) -> dict[str, Any] | None:
    if preferences.get("analysis_focus") != "hockey_props":
        return None
    table_rows = _analysis_candidate_rows(candidates, sports={"nhl"}, preferences=preferences)
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


def _comparison_analysis_views(candidates: list[dict[str, Any]], preferences: dict[str, Any]) -> dict[str, Any] | None:
    requested_subjects = [str(item).strip().lower() for item in (preferences.get("requested_subjects") or []) if str(item).strip()]
    if not preferences.get("comparison_requested") or len(requested_subjects) < 2:
        return None

    table_rows: list[dict[str, Any]] = []
    chart_rows: list[dict[str, Any]] = []
    for index, subject_key in enumerate(requested_subjects[:6], start=1):
        candidate = next((item for item in candidates if _candidate_subject_key(item) == subject_key), None)
        if not isinstance(candidate, dict):
            continue
        row = _candidate_analysis_row(candidate, index)
        row["subject"] = " ".join(part.capitalize() for part in subject_key.split())
        table_rows.append(row)
        chart_rows.append(
            {
                "label": row["subject"],
                "score": row.get("score"),
                "market_fit_score": row.get("market_fit_score"),
                "price_edge_pct": row.get("price_edge_pct"),
            }
        )
    if len(table_rows) < 2:
        return None

    return {
        "focus": "subject_comparison",
        "title": "Target comparison",
        "table": {
            "title": "Side-by-side comparison",
            "columns": ["rank", "subject", "sport", "matchup", "market", "pick", "line", "odds", "confidence", "score", "market_fit_score", "why"],
            "rows": table_rows,
        },
        "chart": {
            "title": "Comparison score grid",
            "type": "bar",
            "x_key": "label",
            "series": ["score", "market_fit_score", "price_edge_pct"],
            "rows": chart_rows,
        },
    }


def _analysis_views_for_query(candidates: list[dict[str, Any]], preferences: dict[str, Any]) -> dict[str, Any] | None:
    comparison_view = _comparison_analysis_views(candidates, preferences)
    if comparison_view is not None:
        return comparison_view
    return _runtime_build_analysis_views(
        candidates,
        preferences,
        build_mlb_home_run_analysis_views=_mlb_home_run_analysis_views,
        mlb_statcast_market_text=_mlb_statcast_market_text,
        safe_text=_safe_text,
        candidate_market_focuses=_candidate_market_focuses,
        advanced_signal_text=_advanced_signal_text,
    )


def _extract_american_odds_range(text: str, *, require_parlay_context: bool = False) -> tuple[int | None, int | None]:
    patterns = [
        r"between\s*([+-]\d+)\s*(?:and|to|through)\s*([+-]\d+)",
        r"([+-]\d+)\s*(?:to|through|-)\s*([+-]\d+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            span_start = max(0, match.start() - 32)
            span_end = min(len(text), match.end() + 32)
            window = text[span_start:span_end]
            if require_parlay_context and not any(token in window for token in ("parlay", "combined", "same ticket")):
                continue
            try:
                first = int(match.group(1))
                second = int(match.group(2))
            except Exception:
                continue
            return (min(first, second), max(first, second))
    return (None, None)


def _american_odds_match(american_odds: float | int | None, preferences: dict[str, Any], *, parlay: bool = False) -> bool:
    if american_odds is None:
        return not any(
            preferences.get(key) is not None or preferences.get(key) is True
            for key in (
                "plus_money_only",
                "candidate_odds_min",
                "candidate_odds_max",
                "favorite_floor",
                "parlay_odds_min",
                "parlay_odds_max",
            )
        )

    value = float(american_odds)
    if parlay:
        parlay_min = preferences.get("parlay_odds_min")
        parlay_max = preferences.get("parlay_odds_max")
        if parlay_min is not None and value < float(parlay_min):
            return False
        if parlay_max is not None and value > float(parlay_max):
            return False
        return True

    if preferences.get("plus_money_only") and value < 100.0:
        return False
    favorite_floor = preferences.get("favorite_floor")
    if favorite_floor is not None and value < float(favorite_floor):
        return False
    candidate_min = preferences.get("candidate_odds_min")
    if candidate_min is not None and value < float(candidate_min):
        return False
    candidate_max = preferences.get("candidate_odds_max")
    if candidate_max is not None and value > float(candidate_max):
        return False
    return True


def _parse_parlay_leg_token(value: str | None) -> int | None:
    token = str(value or "").strip().lower()
    count = _PARLAY_LEG_WORDS.get(token)
    if count is None:
        return None
    return max(2, min(5, int(count)))


def _extract_parlay_leg_preferences(text: str) -> tuple[int | None, int | None]:
    lowered = str(text or "").lower()
    range_match = re.search(
        r"\b(?P<first>two|three|four|five|[2-5])\s*(?:-|to|through|and)\s*(?P<second>two|three|four|five|[2-5])\s*[-\s]*(?:leg|legs|legger)\b",
        lowered,
    )
    if range_match:
        first = _parse_parlay_leg_token(range_match.group("first"))
        second = _parse_parlay_leg_token(range_match.group("second"))
        if first is not None and second is not None:
            return (min(first, second), max(first, second))

    exact_match = re.search(r"\b(?P<count>two|three|four|five|[2-5])\s*[-\s]?(?:leg|legs|legger)\b", lowered)
    if exact_match:
        count = _parse_parlay_leg_token(exact_match.group("count"))
        if count is not None:
            return (count, count)
    return (None, None)


def _extract_round_robin_unit(text: str) -> int | None:
    lowered = str(text or "").lower()
    match = re.search(r"\b(?P<count>[2-4])s\s+round robin\b", lowered)
    if not match:
        match = re.search(r"\bround robin(?:\s+by\s+|\s+using\s+)(?P<count>[2-4])s\b", lowered)
    if not match:
        return None
    return max(2, min(4, int(match.group("count"))))


def _extract_bankroll_amount(text: str) -> int | None:
    lowered = str(text or "").lower()
    match = re.search(r"\b(?:bankroll|roll|budget)\s*(?:of|is)?\s*\$\s*(?P<amount>\d{2,6})\b", lowered)
    if not match:
        match = re.search(r"\$\s*(?P<amount>\d{2,6})\s*(?:bankroll|roll|budget)\b", lowered)
    if not match:
        return None
    return int(match.group("amount"))


def _extract_max_exposure_preferences(text: str) -> tuple[int | None, int | None]:
    lowered = str(text or "").lower()
    pct_match = re.search(r"\b(?:max(?:imum)?|cap|limit)\s*(?:exposure|risk)\s*(?:of|at)?\s*(?P<pct>\d{1,2})\s*%", lowered)
    if not pct_match:
        pct_match = re.search(r"\b(?P<pct>\d{1,2})\s*%\s*(?:max(?:imum)?\s*)?(?:exposure|risk)\b", lowered)
    amount_match = re.search(r"\b(?:max(?:imum)?|cap|limit)\s*(?:exposure|risk)\s*(?:of|at)?\s*\$\s*(?P<amount>\d{1,6})", lowered)
    if not amount_match:
        amount_match = re.search(r"\$\s*(?P<amount>\d{1,6})\s*(?:max(?:imum)?\s*)?(?:exposure|risk)\b", lowered)
    max_pct = int(pct_match.group("pct")) if pct_match else None
    max_amount = int(amount_match.group("amount")) if amount_match else None
    return (max_pct, max_amount)


def _extract_market_focuses(text: str) -> list[str]:
    matches: list[str] = []
    for key, aliases in _MARKET_FOCUS_ALIASES.items():
        if any(_text_has_market_alias(text, alias) for alias in aliases):
            matches.append(key)
    if "total_bases" in matches and "total" in matches:
        matches = [key for key in matches if key != "total"]
    return matches


def _extract_parlay_structure_preferences(text: str) -> dict[str, Any]:
    lowered = str(text or "").lower()
    parlay_type = "standard"
    if "round robin" in lowered:
        parlay_type = "round_robin"
    elif re.search(r"\b(?:same game|same-game|sgp)\b", lowered):
        parlay_type = "same_game"

    cross_sport_required = bool(re.search(r"\b(?:cross[-\s]?sport|multi[-\s]?sport|across sports?)\b", lowered))

    has_conservative_risk = any(token in lowered for token in _CONSERVATIVE_RISK_TOKENS)
    has_aggressive_risk = any(token in lowered for token in _AGGRESSIVE_RISK_TOKENS)

    risk_profile = "balanced"
    if has_conservative_risk and has_aggressive_risk and _question_requests_comparison(lowered):
        risk_profile = "balanced"
    elif has_conservative_risk:
        risk_profile = "conservative"
    elif has_aggressive_risk:
        risk_profile = "aggressive"

    correlation_tolerance = "medium"
    correlation_explicit = False
    if any(token in lowered for token in _LOW_CORRELATION_TOKENS):
        correlation_tolerance = "low"
        correlation_explicit = True
    elif any(token in lowered for token in _MEDIUM_CORRELATION_TOKENS):
        correlation_tolerance = "medium"
        correlation_explicit = True
    elif any(token in lowered for token in _HIGH_CORRELATION_TOKENS) or parlay_type == "same_game":
        correlation_tolerance = "high"
        correlation_explicit = True

    round_robin_unit = _extract_round_robin_unit(lowered) if parlay_type == "round_robin" else None
    if parlay_type == "round_robin" and round_robin_unit is None:
        round_robin_unit = 2
    bankroll_amount = _extract_bankroll_amount(lowered)
    max_exposure_pct, max_exposure_amount = _extract_max_exposure_preferences(lowered)

    return {
        "parlay_type": parlay_type,
        "cross_sport_required": cross_sport_required,
        "risk_profile": risk_profile,
        "correlation_tolerance": correlation_tolerance,
        "correlation_explicit": correlation_explicit,
        "round_robin_unit": round_robin_unit,
        "bankroll_amount": bankroll_amount,
        "max_exposure_pct": max_exposure_pct,
        "max_exposure_amount": max_exposure_amount,
    }


def _parlay_request_summary(preferences: dict[str, Any]) -> dict[str, Any]:
    requested_sports = [str(slug).upper() for slug in (preferences.get("requested_sports") or []) if str(slug).strip()]
    requested_markets = _market_focus_labels(preferences.get("requested_markets") or [])
    requested_subjects = [
        " ".join(part.capitalize() for part in str(subject).split())
        for subject in (preferences.get("requested_subjects") or [])
        if str(subject).strip()
    ]
    requested_date = _safe_text(preferences.get("requested_date"), "")
    board_scope: list[str] = []
    if preferences.get("include_props"):
        board_scope.append("Props")
    if preferences.get("include_games"):
        board_scope.append("Games")

    timing = "Live + pregame"
    if preferences.get("live_only"):
        timing = "Live only"
    elif preferences.get("pregame_only"):
        timing = "Pregame only"

    leg_min = preferences.get("parlay_leg_min")
    leg_max = preferences.get("parlay_leg_max")
    leg_window = None
    if leg_min is not None and leg_max is not None:
        leg_window = f"{leg_min} legs" if int(leg_min) == int(leg_max) else f"{leg_min}-{leg_max} legs"

    parlay_type = _safe_text(preferences.get("parlay_type"), "standard")
    type_label = {
        "standard": "Standard parlay",
        "same_game": "Same-game parlay",
        "round_robin": "Round robin",
    }.get(parlay_type, "Standard parlay")

    chips = [type_label, timing]
    if board_scope:
        chips.extend(board_scope)
    if requested_sports:
        chips.append("/".join(requested_sports))
    chips.extend(requested_markets)
    chips.extend(requested_subjects[:3])
    if requested_date:
        chips.append(requested_date)
    if leg_window:
        chips.append(leg_window)
    if preferences.get("cross_sport_required"):
        chips.append("Cross-sport")
    chips.append(f"{_safe_text(preferences.get('risk_profile'), 'balanced').capitalize()} risk")
    chips.append(f"{_safe_text(preferences.get('correlation_tolerance'), 'medium').capitalize()} correlation")
    if preferences.get("parlay_type") == "round_robin":
        unit = preferences.get("round_robin_unit") or 2
        chips.append(f"{unit}-leg tickets")
    if preferences.get("bankroll_amount") is not None:
        chips.append(f"${int(preferences.get('bankroll_amount'))} bankroll")
    if preferences.get("max_exposure_pct") is not None:
        chips.append(f"Max {int(preferences.get('max_exposure_pct'))}% exposure")
    if preferences.get("max_exposure_amount") is not None:
        chips.append(f"Max ${int(preferences.get('max_exposure_amount'))} exposure")

    return {
        "intent": _safe_text(preferences.get("intent"), "best_bets"),
        "sports": requested_sports,
        "requested_markets": requested_markets,
        "requested_subjects": requested_subjects,
        "requested_date": requested_date or None,
        "timing": timing,
        "board_scope": board_scope,
        "parlay_type": parlay_type,
        "leg_window": leg_window,
        "cross_sport_required": bool(preferences.get("cross_sport_required")),
        "risk_profile": _safe_text(preferences.get("risk_profile"), "balanced"),
        "correlation_tolerance": _safe_text(preferences.get("correlation_tolerance"), "medium"),
        "round_robin_unit": preferences.get("round_robin_unit"),
        "bankroll_amount": preferences.get("bankroll_amount"),
        "max_exposure_pct": preferences.get("max_exposure_pct"),
        "max_exposure_amount": preferences.get("max_exposure_amount"),
        "chips": chips,
    }


@lru_cache(maxsize=1)
def _tracked_repo_files() -> set[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(_repo_root()), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return set()
    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}


def _query_preferences(question: str, *, mode: str | None = None, sport: str | None = None, limit: int | None = None) -> dict[str, Any]:
    lowered = str(question or "").lower()
    explicit_mode = str(mode or "").strip().lower()
    explicit_sport = str(sport or "").strip().lower()
    parlay_structure = _extract_parlay_structure_preferences(lowered)

    requested_sports = set()
    if explicit_sport:
        requested_sports.add(explicit_sport)
    for slug, keywords in _SPORT_KEYWORDS.items():
        if any(_text_contains_keyword(lowered, keyword) for keyword in keywords):
            requested_sports.add(slug)

    requested_markets = _extract_market_focuses(lowered)
    requested_market_set = set(requested_markets)
    if not requested_sports:
        for market_key in requested_markets:
            for slug in _MARKET_DEFAULT_SPORTS.get(market_key, ()): 
                requested_sports.add(slug)

    intent = "best_bets"
    if explicit_mode in {"parlay", "parlays"} or "parlay" in lowered or parlay_structure.get("parlay_type") != "standard":
        intent = "parlay"
    elif explicit_mode in {"live", "live_bets"} or "live bet" in lowered or "in-game" in lowered or "live board" in lowered:
        intent = "live_bets"
    elif explicit_mode in {"pregame", "pregame_bets"} or "pregame" in lowered:
        intent = "pregame_bets"

    live_requested = bool(re.search(r"\b(?:live|in-game|in game|live board)\b", lowered)) or explicit_mode in {"live", "live_bets"}
    pregame_requested = "pregame" in lowered or explicit_mode in {"pregame", "pregame_bets"}
    live_only = intent == "live_bets" or (live_requested and not pregame_requested)
    pregame_only = intent == "pregame_bets" or (pregame_requested and not live_requested)
    if "live and pregame" in lowered or "pregame and live" in lowered:
        live_only = False
        pregame_only = False

    prop_market_requested = bool(requested_market_set - _GAME_SIDE_MARKETS)
    game_market_requested = bool(requested_market_set & _GAME_SIDE_MARKETS)
    include_props = any(keyword in lowered for keyword in _PROP_MARKET_KEYWORDS) or prop_market_requested
    include_games = any(keyword in lowered for keyword in _GAME_MARKET_KEYWORDS)
    if prop_market_requested and not game_market_requested:
        include_games = False
    if explicit_mode in {"game", "games"}:
        include_games = True
    if explicit_mode in {"prop", "props"}:
        include_props = True
    if not include_props and not include_games:
        include_props = True
        include_games = True

    requested_limit = int(limit or 0) if str(limit or "").strip() else 0
    if requested_limit <= 0:
        match = re.search(r"\b(?:top|best)\s+(\d+)\b", lowered)
        if match:
            requested_limit = int(match.group(1))
    if requested_limit <= 0:
        requested_limit = 5

    plus_money_only = any(token in lowered for token in ("plus money", "plus-money", "plus odds"))
    favorite_floor = None
    favorite_cap_match = re.search(r"(?:under|below|up to|max(?:imum)?|no worse than|better than)\s*(-\d+)", lowered)
    if favorite_cap_match:
        favorite_floor = int(favorite_cap_match.group(1))

    candidate_odds_min = None
    candidate_odds_max = None
    min_match = re.search(r"(?:over|above|at least|min(?:imum)?)\s*(\+\d+)", lowered)
    if min_match:
        candidate_odds_min = int(min_match.group(1))
    max_match = re.search(r"(?:under|below|up to|max(?:imum)?)\s*(\+\d+)", lowered)
    if max_match:
        candidate_odds_max = int(max_match.group(1))

    parlay_odds_min, parlay_odds_max = _extract_american_odds_range(lowered, require_parlay_context=True)
    parlay_leg_min, parlay_leg_max = _extract_parlay_leg_preferences(lowered)
    requested_date = _question_requested_date(question)
    analysis_focus = _analysis_focus_from_question(question, sorted(requested_sports), requested_markets)
    comparison_requested = _question_requests_comparison(question)
    wants_table = _question_requests_table(question) or analysis_focus is not None
    wants_chart = _question_requests_chart(question) or analysis_focus is not None

    return {
        "intent": intent,
        "requested_sports": sorted(requested_sports),
        "requested_markets": requested_markets,
        "include_props": include_props,
        "include_games": include_games,
        "live_only": live_only,
        "pregame_only": pregame_only,
        "plus_money_only": plus_money_only,
        "favorite_floor": favorite_floor,
        "candidate_odds_min": candidate_odds_min,
        "candidate_odds_max": candidate_odds_max,
        "parlay_odds_min": parlay_odds_min,
        "parlay_odds_max": parlay_odds_max,
        "parlay_leg_min": parlay_leg_min,
        "parlay_leg_max": parlay_leg_max,
        "parlay_type": parlay_structure["parlay_type"],
        "cross_sport_required": parlay_structure["cross_sport_required"],
        "risk_profile": parlay_structure["risk_profile"],
        "correlation_tolerance": parlay_structure["correlation_tolerance"],
        "correlation_explicit": parlay_structure["correlation_explicit"],
        "round_robin_unit": parlay_structure["round_robin_unit"],
        "bankroll_amount": parlay_structure["bankroll_amount"],
        "max_exposure_pct": parlay_structure["max_exposure_pct"],
        "max_exposure_amount": parlay_structure["max_exposure_amount"],
        "analysis_focus": analysis_focus,
        "comparison_requested": comparison_requested,
        "requested_subjects": [],
        "requested_date": requested_date,
        "wants_table": wants_table,
        "wants_chart": wants_chart,
        "limit": max(1, min(requested_limit, 10)),
        "question": str(question or "").strip(),
    }


def build_intelligence_overview(*, selected_date: str | None = None, force_refresh: bool = False) -> list[dict[str, Any]]:
    effective_date = _effective_date(selected_date)
    sports = current_app.config.get("SYNDICATE_SPORTS", [])
    overview: list[dict[str, Any]] = []
    for sport in sports:
        if not isinstance(sport, dict):
            continue
        try:
            overview.append(
                _build_sport_overview(
                    sport,
                    effective_date,
                    force_refresh=force_refresh,
                    preserve_requested_date=True,
                )
            )
        except Exception as exc:
            overview.append(
                {
                    **sport,
                    "context_label": effective_date,
                    "data_health": "error",
                    "data_warnings": [f"Overview build failed: {exc}"],
                    "home_rails": {"pregame": {"items": []}, "live": {"items": []}, "compact": {"items": []}},
                    "dashboard_games": [],
                }
            )
    return overview


def _status_context_label_for_sport(slug: str, effective_date: str) -> str:
    slug = str(slug or "").strip().lower()
    if slug in {"mlb", "nba", "wnba", "nhl", "ncaab"}:
        return effective_date
    if slug == "nfl":
        tracked_week = nfl_sources.tracked_week() or {}
        season_value = tracked_week.get("season")
        week_value = tracked_week.get("week")
        if isinstance(season_value, int) and isinstance(week_value, int):
            return f"{season_value} Week {week_value}"
        season_value = nfl_sources.latest_season()
        week_value = nfl_sources.default_week(season_value)
        return f"{season_value} Week {week_value}"
    if slug == "ncaaf":
        week_summaries = ncaaf_sources.week_summaries()
        if week_summaries:
            latest = week_summaries[-1]
            return f"{int(latest.get('season') or ncaaf_sources.default_season())} Week {int(latest.get('week') or ncaaf_sources.default_week())}"
        return f"{ncaaf_sources.default_season()} Week {ncaaf_sources.default_week()}"
    return effective_date


def _status_overview_rows(*, selected_date: str | None = None) -> list[dict[str, Any]]:
    effective_date = _effective_date(selected_date)
    sports = current_app.config.get("SYNDICATE_SPORTS", [])
    overview: list[dict[str, Any]] = []
    for sport in sports:
        if not isinstance(sport, dict):
            continue
        slug = _safe_text(sport.get("slug"), "sport").lower()
        context_label = _status_context_label_for_sport(slug, effective_date)
        overview.append(
            {
                **sport,
                "slug": slug,
                "name": _safe_text(sport.get("name"), slug.upper()),
                "context_label": context_label,
                "data_health": "status",
                "data_warnings": [],
                "active_today": context_label == effective_date,
            }
        )
    return overview


def _artifact_specs_for_sport(sport: dict[str, Any]) -> list[tuple[str, Path]]:
    slug = str(sport.get("slug") or "").strip().lower()
    context_label = str(sport.get("context_label") or "").strip()
    if slug == "mlb" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label):
        season = int(context_label[:4])
        return [
            ("Live lens report", _mlb_repo_artifact_path("data", "live_lens", f"live_lens_report_{context_label.replace('-', '_')}.json")),
            ("Live lens log", _mlb_repo_artifact_path("data", "live_lens", f"live_lens_{context_label.replace('-', '_')}.jsonl")),
            (
                "Season betting day",
                _mlb_repo_artifact_path(
                    "data",
                    "eval",
                    "seasons",
                    str(season),
                    "betting_day_payloads_retuned",
                    f"season_betting_day_{season}_{context_label.replace('-', '_')[5:]}.json",
                ),
            ),
        ]
    if slug == "nba" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label):
        season = int(context_label[:4])
        return [
            ("Recommendations slate", nba_processed_path(f"recommendations_slate_{context_label}.json")),
            ("Props recommendations", nba_processed_path(f"props_recommendations_{context_label}.csv")),
            ("Live state snapshot", nba_live_snapshot_path(f"live_state_{context_label}.jsonl")),
            ("Season betting day", nba_season_betting_card_day_path(season, context_label, profile="retuned")),
        ]
    if slug == "wnba" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label):
        season = int(context_label[:4])
        return [
            ("Recommendations slate", wnba_processed_path(f"recommendations_slate_{context_label}.json")),
            ("Props recommendations", wnba_processed_path(f"props_recommendations_{context_label}.csv")),
            ("Live state snapshot", wnba_live_snapshot_path(f"live_state_{context_label}.jsonl")),
            ("Season betting day", wnba_processed_path(f"season_betting_card_day_{season}_retuned_{context_label}.json")),
        ]
    if slug == "nhl" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label):
        return [
            ("Recommendations", nhl_recommendation_path(context_label)),
            ("Props recommendations", nhl_processed_path(f"props_recommendations_{context_label}.csv")),
            ("Scoreboard snapshot", nhl_scoreboard_snapshot_path(context_label)),
            ("Props lines snapshot", nhl_props_lines_snapshot_path(context_label)),
        ]
    if slug == "nfl":
        week_match = re.search(r"(?P<season>\d{4})\s+Week\s+(?P<week>\d+)", context_label)
        if week_match:
            season = int(week_match.group("season"))
            week = int(week_match.group("week"))
            return [
                ("Weekly recommendations", nfl_sources.recommendation_path(week, season=season)),
                ("Current week", nfl_sources.data_path("current_week.json")),
            ]
    if slug == "ncaaf":
        week_match = re.search(r"(?P<season>\d{4})\s+Week\s+(?P<week>\d+)", context_label)
        if week_match:
            week = int(week_match.group("week"))
            return [
                ("Recommendation summary", ncaaf_sources.summary_path(week)),
                ("Summary index", ncaaf_sources.data_path("recommendations_summary", "index.json")),
            ]
    if slug == "ncaab" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label):
        root = ncaab_sources._source_roots()[0]
        return [
            ("Recommendations", root / "api" / "recommendations" / f"recommendations_{context_label}.json"),
            ("Live state", root / "api" / "live_state" / f"live_state_{context_label}.json"),
            ("Live lines", root / "api" / "live_lines" / f"live_lines_{context_label}.json"),
        ]
    return []


def _mlb_repo_artifact_path(*parts: str) -> Path:
    return default_mlb_source_root().joinpath(*parts)


def _path_status(path: Path, tracked: set[str]) -> dict[str, Any]:
    relative_path = _relative_repo_path(path)
    inside_repo = not Path(relative_path).is_absolute() and not relative_path.startswith("..")
    exists = False
    try:
        exists = path.exists()
    except OSError:
        exists = False
    tracked_here = inside_repo and relative_path in tracked
    return {
        "path": relative_path,
        "exists": exists,
        "tracked": tracked_here,
        "inside_repo": inside_repo,
    }


def _coerce_date_token(value: str) -> str | None:
    match = _DATE_TOKEN_RE.search(str(value or ""))
    if not match:
        return None
    token = match.group("date")
    if re.fullmatch(r"\d{8}", token):
        return f"{token[:4]}-{token[4:6]}-{token[6:8]}"
    return token


def _question_requested_date(question: str) -> str | None:
    lowered = str(question or "").strip().lower()
    if not lowered:
        return None
    explicit = _coerce_date_token(lowered)
    if explicit:
        return explicit
    today_value = central_today_iso()
    if re.search(r"\btoday\b", lowered):
        return today_value
    if re.search(r"\btomorrow\b", lowered):
        return (date.fromisoformat(today_value) + timedelta(days=1)).isoformat()
    if re.search(r"\byesterday\b", lowered):
        return (date.fromisoformat(today_value) - timedelta(days=1)).isoformat()
    return None


def _latest_matching_path(directory: Path, pattern: str, *, requested_date: str | None = None) -> Path | None:
    try:
        candidates = [path for path in directory.glob(pattern) if path.is_file()]
    except OSError:
        return None
    if not candidates:
        return None
    requested = str(requested_date or "").strip() or None
    dated: list[tuple[str, Path]] = []
    for path in candidates:
        token = _coerce_date_token(path.name)
        if token is None:
            continue
        if requested and token > requested:
            continue
        dated.append((token, path))
    if dated:
        dated.sort(key=lambda item: item[0])
        return dated[-1][1]
    return max(candidates, key=lambda item: item.name)


def _nba_live_lens_path(filename: str) -> Path:
    processed_root = nba_processed_path("team_advanced_stats_2026.csv").parents[1]
    return processed_root / "live_lens" / filename


def _wnba_live_lens_path(filename: str) -> Path:
    processed_root = wnba_processed_path("recommendations_slate_2026-06-04.json").parents[1]
    return processed_root / "live_lens" / filename


def _resolve_nba_props_predictions_path(context_label: str) -> Path:
    direct = nba_processed_path(f"props_predictions_{context_label}.csv")
    if direct.exists():
        return direct
    return _latest_matching_path(direct.parent, "props_predictions_*.csv", requested_date=context_label) or direct


def _resolve_nba_live_context_path(context_label: str) -> Path:
    direct = _nba_live_lens_path(f"live_lens_projections_{context_label}.jsonl")
    if direct.exists():
        return direct
    return _latest_matching_path(direct.parent, "live_lens_projections_*.jsonl", requested_date=context_label) or direct


def _resolve_nba_live_pbp_context_path(context_label: str) -> Path:
    direct = nba_live_snapshot_path(f"live_pbp_stats_{context_label}.jsonl")
    if direct.exists():
        return direct
    return _latest_matching_path(direct.parent, "live_pbp_stats_*.jsonl", requested_date=context_label) or direct


def _resolve_wnba_live_context_path(context_label: str) -> Path:
    direct = _wnba_live_lens_path(f"live_lens_projections_{context_label}.jsonl")
    if direct.exists():
        return direct
    return _latest_matching_path(direct.parent, "live_lens_projections_*.jsonl", requested_date=context_label) or direct


def _resolve_wnba_live_pbp_context_path(context_label: str) -> Path:
    direct = wnba_live_snapshot_path(f"live_pbp_stats_{context_label}.jsonl")
    if direct.exists():
        return direct
    return _latest_matching_path(direct.parent, "live_pbp_stats_*.jsonl", requested_date=context_label) or direct


def _resolve_ncaab_live_pbp_context_path(context_label: str) -> Path:
    root = ncaab_sources._source_roots()[0]
    by_date_root = root / "raw_outputs" / "by_date"
    direct = by_date_root / context_label / f"live_features_{context_label}.csv"
    if direct.exists():
        return direct
    return _latest_matching_path(by_date_root, "*/live_features_*.csv", requested_date=context_label) or direct


def _resolve_nhl_scoreboard_context_path(context_label: str) -> Path:
    direct = nhl_scoreboard_snapshot_path(context_label)
    if direct.exists():
        return direct
    games_root = direct.parents[1]
    return _latest_matching_path(games_root, "date=*/scoreboard.csv", requested_date=context_label) or direct


def _resolve_nhl_shift_context_path(context_label: str) -> Path:
    direct = nhl_processed_path(f"shifts_{context_label}.csv")
    if direct.exists():
        return direct
    return _latest_matching_path(direct.parent, "shifts_*.csv", requested_date=context_label) or direct


def _advanced_input_rows_for_sport(sport: dict[str, Any], tracked: set[str]) -> list[dict[str, Any]]:
    advanced_rows: list[dict[str, Any]] = []
    for spec in _advanced_input_specs_for_sport(sport):
        status = _path_status(spec["path"], tracked)
        advanced_rows.append(
            {
                "label": str(spec.get("label") or "Advanced input"),
                "metrics": [str(metric).strip() for metric in (spec.get("metrics") or []) if str(metric).strip()],
                **status,
            }
        )
    return advanced_rows


def _available_advanced_inputs_for_sport(sport: dict[str, Any], tracked: set[str] | None = None) -> list[dict[str, Any]]:
    resolved_tracked = tracked if tracked is not None else _tracked_repo_files()
    rows = _advanced_input_rows_for_sport(sport, resolved_tracked)
    return [row for row in rows if bool(row.get("exists"))]


def _advanced_readiness_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    required_rows = [row for row in rows if bool(row.get("inside_repo"))]
    tracked_rows = [row for row in required_rows if bool(row.get("tracked"))]
    exists_rows = [row for row in required_rows if bool(row.get("exists"))]
    total = len(required_rows)
    tracked_count = len(tracked_rows)
    exists_count = len(exists_rows)
    ratio = float(exists_count / total) if total else (1.0 if rows else 0.0)
    missing = [
        {
            "label": _safe_text(row.get("label"), "Advanced input"),
            "path": _safe_text(row.get("path"), "-"),
            "missing_reason": "missing",
        }
        for row in rows
        if row.get("inside_repo") and not row.get("exists")
    ]
    publish_missing = [
        {
            "label": _safe_text(row.get("label"), "Advanced input"),
            "path": _safe_text(row.get("path"), "-"),
            "missing_reason": "untracked",
        }
        for row in rows
        if row.get("inside_repo") and row.get("exists") and not row.get("tracked")
    ]
    return {
        "required_total": total,
        "tracked_count": tracked_count,
        "exists_count": exists_count,
        "ratio": round(ratio, 3),
        "ready": bool(rows) and not missing,
        "missing_inputs": missing,
        "publish_missing_inputs": publish_missing,
    }


def _advanced_score_adjustment(summary: dict[str, Any]) -> float:
    ratio = float(summary.get("ratio") or 0.0)
    if bool(summary.get("ready")):
        return 6.0
    if ratio >= 0.75:
        return 2.5
    if ratio >= 0.5:
        return 0.0
    if ratio > 0.0:
        return -3.5
    return -7.5


def _readiness_label(summary: dict[str, Any]) -> str:
    if bool(summary.get("ready")):
        return "ready"
    ratio = float(summary.get("ratio") or 0.0)
    if ratio >= 0.5:
        return "partial"
    return "blocked"


def _build_readiness_gate(overview: list[dict[str, Any]], tracked: set[str]) -> dict[str, Any]:
    sport_rows: list[dict[str, Any]] = []
    for sport in overview:
        if not isinstance(sport, dict):
            continue
        slug = _safe_text(sport.get("slug"), "sport").lower()
        active_today = bool(sport.get("active_today"))
        advanced_rows = _advanced_input_rows_for_sport(sport, tracked)
        summary = _advanced_readiness_summary(advanced_rows)
        status = "inactive" if not active_today else _readiness_label(summary)
        sport_rows.append(
            {
                "slug": slug,
                "name": _safe_text(sport.get("name"), slug.upper()),
                "status": status,
                "active_today": active_today,
                "advanced_ready": bool(summary.get("ready")),
                "required_total": int(summary.get("required_total") or 0),
                "tracked_count": int(summary.get("tracked_count") or 0),
                "exists_count": int(summary.get("exists_count") or 0),
                "missing_inputs": summary.get("missing_inputs") or [],
                "publish_missing_inputs": summary.get("publish_missing_inputs") or [],
            }
        )
    ready = [row for row in sport_rows if row.get("status") == "ready"]
    blocked = [row for row in sport_rows if row.get("status") == "blocked"]
    partial = [row for row in sport_rows if row.get("status") == "partial"]
    inactive = [row for row in sport_rows if row.get("status") == "inactive"]
    return {
        "ready": not blocked,
        "ready_sports": [row.get("slug") for row in ready],
        "partial_sports": [row.get("slug") for row in partial],
        "blocked_sports": [row.get("slug") for row in blocked],
        "inactive_sports": [row.get("slug") for row in inactive],
        "sports": sport_rows,
    }


def _advanced_driver_text(rows: list[dict[str, Any]], *, limit_groups: int = 2, limit_metrics: int = 3) -> str:
    if not rows:
        return ""
    groups: list[str] = []
    for row in rows[:limit_groups]:
        metrics = [str(metric).strip() for metric in (row.get("metrics") or []) if str(metric).strip()][:limit_metrics]
        if metrics:
            groups.append(f"{row.get('label')}: {', '.join(metrics)}")
        else:
            groups.append(str(row.get("label") or "Advanced inputs"))
    return "; ".join(groups)


def _advanced_input_specs_for_sport(sport: dict[str, Any]) -> list[dict[str, Any]]:
    slug = str(sport.get("slug") or "").strip().lower()
    context_label = str(sport.get("context_label") or "").strip()
    season = None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label):
        season = int(context_label[:4])

    if slug == "mlb":
        return [
            {
                "label": "Statcast batter and pitcher features",
                "metrics": ["Launch angle", "Exit velocity", "Barrel rate", "Hard-hit rate", "Pitch mix"],
                "path": _mlb_repo_artifact_path("data", "statcast", "features", "player_features_latest.json"),
            },
            {
                "label": "Live lens and betting-day synthesis",
                "metrics": ["Live projection delta", "Hit pace", "Ladder viability", "Board edge", "Sim confidence"],
                "path": _mlb_repo_artifact_path("data", "live_lens", f"live_lens_report_{context_label.replace('-', '_')}.json") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label) else _mlb_repo_artifact_path("data", "live_lens"),
            },
        ]
    if slug == "nba" and season is not None:
        return [
            {
                "label": "Team advanced stats",
                "metrics": ["Pace", "Offensive rating", "Defensive rating", "Shot profile", "Rebound environment"],
                "path": nba_processed_path(f"team_advanced_stats_{season}.csv"),
            },
            {
                "label": "Play-by-play live recap",
                "metrics": ["Recent scoring run", "Possession estimate", "Shot mix", "Quarter scoring", "Live sequence pressure"],
                "path": _resolve_nba_live_pbp_context_path(context_label),
            },
            {
                "label": "Player prop model outputs",
                "metrics": ["Usage context", "Minute expectation", "Prop mean", "Edge vs line", "Calibration"],
                "path": _resolve_nba_props_predictions_path(context_label),
            },
            {
                "label": "Live state and pace context",
                "metrics": ["Live pace", "Game state", "In-game line movement", "Board pressure", "Possession context"],
                "path": _resolve_nba_live_context_path(context_label),
            },
        ]
    if slug == "wnba" and season is not None:
        return [
            {
                "label": "Team environment and pace layer",
                "metrics": ["Pace", "Team environment", "Shot volume context", "Possession profile", "Matchup pressure"],
                "path": wnba_processed_path(f"recommendations_slate_{context_label}.json"),
            },
            {
                "label": "Play-by-play live recap",
                "metrics": ["Recent scoring run", "Possession estimate", "Shot mix", "Quarter scoring", "Live sequence pressure"],
                "path": _resolve_wnba_live_pbp_context_path(context_label),
            },
            {
                "label": "Player prop model outputs",
                "metrics": ["Usage context", "Minute expectation", "Prop mean", "Edge vs line", "Calibration"],
                "path": wnba_processed_path(f"props_recommendations_{context_label}.csv"),
            },
            {
                "label": "Live state mirror",
                "metrics": ["Live pace", "Game state", "Rotation pressure", "In-game projection shift", "Board pressure"],
                "path": _resolve_wnba_live_context_path(context_label),
            },
        ]
    if slug == "nhl" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label):
        return [
            {
                "label": "Game recommendation layer",
                "metrics": ["xG proxy last 10", "Goal pace per 60", "SOG pace per 60", "Pressure flags", "Score effects"],
                "path": nhl_recommendation_path(context_label),
            },
            {
                "label": "Shift and on-ice sequence recap",
                "metrics": ["Shift deployment", "On-ice tempo", "Line matching", "Rest state", "TOI pressure"],
                "path": _resolve_nhl_shift_context_path(context_label),
            },
            {
                "label": "Props recommendation layer",
                "metrics": ["Shot volume", "Goalie saves", "Skater opportunity", "Line edge", "Market depth"],
                "path": nhl_processed_path(f"props_recommendations_{context_label}.csv"),
            },
            {
                "label": "Odds and scoreboard context",
                "metrics": ["Live scoreboard state", "Props lines", "Market change", "Game status", "Book context"],
                "path": _resolve_nhl_scoreboard_context_path(context_label),
            },
        ]
    if slug == "nfl":
        tracked_week = nfl_sources.tracked_week() or {}
        season_value = tracked_week.get("season")
        week_value = tracked_week.get("week")
        if isinstance(season_value, int) and isinstance(week_value, int):
            return [
                {
                    "label": "Weekly recommendation snapshot",
                    "metrics": ["Off EPA", "Def EPA", "Pace", "Pass rate", "Market edge"],
                    "path": nfl_sources.recommendation_path(week_value, season=season_value),
                },
                {
                    "label": "Current week context",
                    "metrics": ["Season", "Week", "Publish state", "Board freshness", "Routing context"],
                    "path": nfl_sources.data_path("current_week.json"),
                },
                {
                    "label": "Player props mirror",
                    "metrics": ["Passing yards", "Rushing yards", "Receiving yards", "TD market context", "Book coverage"],
                    "path": nfl_sources.data_path(f"oddsapi_player_props_{season_value}_wk{week_value}.csv"),
                },
            ]
    if slug == "ncaaf":
        week_match = re.search(r"(?P<season>\d{4})\s+Week\s+(?P<week>\d+)", context_label)
        if week_match:
            week = int(week_match.group("week"))
            season_value = int(week_match.group("season"))
            return [
                {
                    "label": "Weekly recommendation summary",
                    "metrics": ["Model spread", "Model total", "Market edge", "Confidence", "Slate coverage"],
                    "path": ncaaf_sources.summary_path(week),
                },
                {
                    "label": "Recommendation index",
                    "metrics": ["Week availability", "Fetch health", "Artifact coverage", "Season routing", "Publish context"],
                    "path": ncaaf_sources.data_path("recommendations_summary", "index.json"),
                },
                {
                    "label": "Enhanced totals export",
                    "metrics": ["Projected total", "Schedule context", "Enhanced totals layer", "Game metadata", "Output freshness"],
                    "path": _repo_root().parent / "NCAAFCompare" / "data" / f"college_football_schedule_{season_value}_predicted_totals_enhanced_20251123T161637Z.csv",
                },
            ]
    if slug == "ncaab" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", context_label):
        root = ncaab_sources._source_roots()[0]
        return [
            {
                "label": "Recommendations mirror",
                "metrics": ["Spread edge", "Total edge", "Confidence", "Board ranking", "Availability"],
                "path": root / "api" / "recommendations" / f"recommendations_{context_label}.json",
            },
            {
                "label": "Play-by-play derived live recap",
                "metrics": ["Possession estimate", "Points per possession", "Turnover pressure", "Rebound pressure", "Live fetch freshness"],
                "path": _resolve_ncaab_live_pbp_context_path(context_label),
            },
            {
                "label": "Live state mirror",
                "metrics": ["Possession state", "Live total context", "Score pressure", "Game status", "Board timing"],
                "path": root / "api" / "live_state" / f"live_state_{context_label}.json",
            },
            {
                "label": "Pace and live-line context",
                "metrics": ["Pace hi", "Pace low", "Live lines", "Possession rate", "Tempo buckets"],
                "path": root / "api" / "live_lines" / f"live_lines_{context_label}.json",
            },
        ]
    return []


def build_intelligence_status(*, selected_date: str | None = None, force_refresh: bool = False) -> dict[str, Any]:
    if force_refresh:
        _tracked_repo_files.cache_clear()
    overview = _status_overview_rows(selected_date=selected_date)
    tracked = _tracked_repo_files()
    sports_status: list[dict[str, Any]] = []
    tracked_ok_count = 0
    tracked_total = 0
    advanced_ready_count = 0
    advanced_total = 0

    for sport in overview:
        artifact_rows: list[dict[str, Any]] = []
        for label, path in _artifact_specs_for_sport(sport):
            status = _path_status(path, tracked)
            if status["inside_repo"]:
                tracked_total += 1
                if status["tracked"]:
                    tracked_ok_count += 1
            artifact_rows.append(
                {
                    "label": label,
                    **status,
                }
            )

        advanced_rows = _advanced_input_rows_for_sport(sport, tracked)
        for status in advanced_rows:
            if status["inside_repo"]:
                advanced_total += 1
                if status["tracked"]:
                    advanced_ready_count += 1

        artifact_exists = any(bool(row.get("exists")) for row in artifact_rows)
        advanced_exists = any(bool(row.get("exists")) for row in advanced_rows)
        active_today = bool(sport.get("active_today")) or artifact_exists or advanced_exists
        data_warnings = [str(item).strip() for item in (sport.get("data_warnings") or []) if str(item).strip()]
        if not artifact_exists and not advanced_exists:
            data_warnings.append("No tracked artifacts or advanced inputs found for this sport context.")
        data_health = "ready" if (artifact_exists or advanced_exists) else "missing"

        sports_status.append(
            {
                "slug": _safe_text(sport.get("slug"), "sport").lower(),
                "name": _safe_text(sport.get("name"), "Sport"),
                "context_label": _safe_text(sport.get("context_label"), _effective_date(selected_date)),
                "data_health": data_health,
                "data_warnings": data_warnings,
                "artifacts": artifact_rows,
                "advanced_inputs": advanced_rows,
                "active_today": active_today,
                "tracked_ready": all(row.get("tracked") for row in artifact_rows if row.get("inside_repo")) if artifact_rows else False,
                "advanced_ready": all(row.get("exists") for row in advanced_rows if row.get("inside_repo")) if advanced_rows else False,
                "advanced_gate": _advanced_readiness_summary(advanced_rows),
            }
        )

    readiness_gate = _build_readiness_gate(overview, tracked)

    return {
        "selected_date": _effective_date(selected_date),
        "sports": sports_status,
        "tracked_summary": {
            "tracked_ok": tracked_ok_count,
            "tracked_total": tracked_total,
        },
        "advanced_summary": {
            "tracked_ok": advanced_ready_count,
            "tracked_total": advanced_total,
        },
        "readiness_gate": readiness_gate,
        "local_only": True,
    }


def _sport_matches_preferences(sport: dict[str, Any], preferences: dict[str, Any]) -> bool:
    requested_sports = preferences.get("requested_sports") or []
    if not requested_sports:
        return True
    return _safe_text(sport.get("slug"), "").lower() in requested_sports


def _prop_candidate_from_item(sport: dict[str, Any], item: dict[str, Any], *, surface_key: str, surface_title: str) -> dict[str, Any]:
    row = _build_prop_dashboard_row(sport, item, default_surface=surface_title)
    projected_value = _numeric_hint(row.get("projected"))
    line_value = _numeric_hint(row.get("line"))
    if projected_value is not None and line_value is not None:
        row["score"] = float(row.get("score", 0.0)) + abs(projected_value - line_value) * 3.0
    advanced_signals = _advanced_signals_from_item(item)
    source_summary = _item_source_summary(item)
    detail_text = _safe_text(item.get("detail"), "") or _safe_text(item.get("why_explain"), "") or _safe_text(item.get("shape_summary"), "")
    summary_text = _safe_text(item.get("summary"), "") or _safe_text(item.get("basketball_summary"), "") or _item_reason_summary(item)
    row.update(
        {
            "candidate_type": "prop",
            "surface_key": surface_key,
            "surface_title": surface_title,
            "sport_slug": _safe_text(sport.get("slug"), "sport").lower(),
            "writeup": source_summary,
            "detail": detail_text,
            "summary": summary_text,
            "status_context": _safe_text(item.get("status_context"), ""),
            "status_display": _safe_text(item.get("status_display"), ""),
            "hero_live_box": item.get("hero_live_box") if isinstance(item.get("hero_live_box"), dict) else None,
            "hero_sim_box": item.get("hero_sim_box") if isinstance(item.get("hero_sim_box"), dict) else None,
            "display_pills": item.get("display_pills") if isinstance(item.get("display_pills"), list) else [],
            "batter_id": _safe_int(item.get("batter_id")),
            "pitcher_id": _safe_int(item.get("pitcher_id")),
            "opponent_pitcher_id": _safe_int(item.get("opponent_pitcher_id")),
            "advanced_signals": advanced_signals,
        }
    )
    return row


def _mlb_home_run_candidates_from_artifact(sport: dict[str, Any]) -> list[dict[str, Any]]:
    if _safe_text(sport.get("slug"), "").lower() != "mlb":
        return []
    selected_date = _safe_text(sport.get("context_label"), "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", selected_date):
        return []
    summary = mlb_load_json_file(mlb_daily_artifact_path(selected_date, suffix="_hr_targets"))
    rows = summary.get("rows") if isinstance((summary or {}).get("rows"), list) else []
    candidates: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:10], start=1):
        if not isinstance(row, dict):
            continue
        hr_probability = _numeric_hint(row.get("p_hr_1plus"))
        support_score = _numeric_hint(row.get("hr_support_raw_score") or row.get("hr_support_score"))
        player_name = _safe_text(row.get("player_name"), "Unknown hitter")
        reasons = [str(item).strip() for item in (row.get("hr_target_reasons") or []) if str(item).strip()]
        writeup = _safe_text(row.get("hr_target_summary"), "") or " ".join(reasons[:2])
        display_pills: list[str] = []
        if hr_probability is not None:
            display_pills.append(f"HR Prob {hr_probability * 100.0:.1f}%")
        if support_score is not None:
            display_pills.append(f"Support {support_score:.0f}")
        lineup_order = _safe_int(row.get("lineup_order"))
        if lineup_order is not None:
            display_pills.append(f"Lineup {lineup_order}")
        advanced_signals = [
            {
                "key": "batter_statcast_hr_mult",
                "label": _humanize_signal_key("batter_statcast_hr_mult"),
                "value": round(float(row.get("batter_platoon_hr_mult")), 3),
            }
            for _ in [0]
            if _numeric_hint(row.get("batter_platoon_hr_mult")) is not None
        ]
        if _numeric_hint(row.get("pitcher_platoon_hr_mult")) is not None:
            advanced_signals.append(
                {
                    "key": "pitcher_statcast_hr_mult",
                    "label": _humanize_signal_key("pitcher_statcast_hr_mult"),
                    "value": round(float(_numeric_hint(row.get("pitcher_platoon_hr_mult")) or 0.0), 3),
                }
            )
        score = float(hr_probability or 0.0) * 100.0 + float(support_score or 0.0) + max(0.0, 12.0 - float(index))
        candidates.append(
            {
                "candidate_type": "prop",
                "sport": _safe_text(sport.get("name"), "MLB"),
                "sport_slug": "mlb",
                "surface_key": "pregame",
                "surface_title": "HR targets",
                "name": player_name,
                "market": "Home Runs",
                "market_key": "home_runs",
                "pick": "Over 0.5",
                "matchup": _safe_text(row.get("matchup"), "-"),
                "team": _safe_text(row.get("team"), "-"),
                "team_key": _safe_text(row.get("team"), "").lower() or None,
                "player_team": _safe_text(row.get("team"), "-"),
                "line": "0.5",
                "odds": "-",
                "projected": "-",
                "confidence": f"{hr_probability * 100.0:.1f}%" if hr_probability is not None else "-",
                "edge": "-",
                "score": score,
                "href": f"/mlb/hr-targets?date={selected_date}",
                "href_label": "Open HR board",
                "writeup": writeup,
                "display_pills": display_pills,
                "advanced_signals": advanced_signals,
                "batter_id": _safe_int(row.get("batter_id")),
                "opponent_pitcher_id": _safe_int(row.get("opponent_pitcher_id")),
                "lineup_order": lineup_order,
                "hr_support_score": support_score,
                "hr_probability": hr_probability,
            }
        )
    return candidates


def _mlb_subject_prop_candidates_from_artifact(
    sport: dict[str, Any],
    *,
    question: str,
    preferences: dict[str, Any],
) -> list[dict[str, Any]]:
    if _safe_text(sport.get("slug"), "").lower() != "mlb":
        return []
    selected_date = _safe_text(sport.get("context_label"), "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", selected_date):
        return []
    normalized_question = _normalized_market_text(question)
    if not normalized_question:
        return []
    requested_markets = {
        str(item).strip().lower()
        for item in (preferences.get("requested_markets") or [])
        if str(item).strip()
    }
    top_props = mlb_load_json_file(mlb_daily_top_props_path(selected_date))
    rows: list[dict[str, Any]] = []
    groups = top_props.get("groups") if isinstance((top_props or {}).get("groups"), dict) else {}
    pitcher_group = groups.get("pitcher") if isinstance(groups.get("pitcher"), dict) else {}
    sections = pitcher_group.get("sections") if isinstance(pitcher_group.get("sections"), list) else []
    for section in sections:
        if not isinstance(section, dict):
            continue
        section_rows = section.get("rows") if isinstance(section.get("rows"), list) else []
        for row in section_rows:
            if isinstance(row, dict):
                rows.append(row)
    pitcher_snapshot = mlb_load_json_file(mlb_daily_snapshot_oddsapi_pitcher_props_path(selected_date))
    pitcher_market_rows = pitcher_snapshot.get("pitcher_props") if isinstance((pitcher_snapshot or {}).get("pitcher_props"), dict) else {}
    candidates: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        player_name = _safe_text(row.get("ownerName") or row.get("playerName"), "")
        normalized_name = _normalized_market_text(player_name)
        if not normalized_name:
            continue
        if not re.search(rf"(?<![a-z0-9]){re.escape(normalized_name)}(?![a-z0-9])", normalized_question):
            continue
        market_key = _market_key_from_text(row.get("stat") or row.get("statLabel"), allow_fallback=True)
        if not market_key:
            continue
        if requested_markets and market_key not in requested_markets:
            continue
        dedupe_key = (normalized_name, market_key)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        snapshot_player = pitcher_market_rows.get(normalized_name) if isinstance(pitcher_market_rows, dict) else None
        snapshot_market = snapshot_player.get(market_key) if isinstance((snapshot_player or {}).get(market_key), dict) else {}
        line_value = _numeric_hint(snapshot_market.get("line"))
        if line_value is None:
            line_value = _numeric_hint(row.get("marketLine") or row.get("line"))
        mean_value = _numeric_hint(row.get("mean"))
        sim_prob = _numeric_hint(row.get("simProb"))
        raw_edge = _numeric_hint(row.get("rawEdge"))
        selection_label = _safe_text(row.get("selectionLabel"), "Over") or "Over"
        selection_direction = 1 if selection_label.lower() == "over" else -1 if selection_label.lower() == "under" else 0
        odds_text = _safe_text(
            snapshot_market.get("over_odds") if selection_direction >= 0 else snapshot_market.get("under_odds"),
            "",
        )
        if not odds_text:
            odds_value = _american_odds_value(row.get("odds"))
            if odds_value is not None:
                odds_text = f"+{int(odds_value)}" if odds_value > 0 else str(int(odds_value))
        matchup = _safe_text(row.get("matchup"), "-")
        market_label = _safe_text(row.get("statLabel"), "") or _market_label(market_key)
        pick = f"{selection_label} {line_value:.1f}" if line_value is not None else selection_label
        projected_text = f"{mean_value:.1f}" if mean_value is not None else "-"
        confidence_text = f"{sim_prob * 100.0:.1f}%" if sim_prob is not None else "-"
        edge_text = f"{raw_edge * 100.0:.1f}%" if raw_edge is not None else "-"
        detail_bits = []
        if mean_value is not None and line_value is not None:
            detail_bits.append(f"Projection {mean_value:.1f} versus line {line_value:.1f}")
        if sim_prob is not None:
            detail_bits.append(f"Sim win probability {sim_prob * 100.0:.1f}%")
        if raw_edge is not None:
            detail_bits.append(f"Raw edge {raw_edge * 100.0:.1f}%")
        score = float(sim_prob or 0.0) * 100.0 + max(0.0, float(raw_edge or 0.0) * 100.0)
        rank_value = _safe_int(row.get("rank"))
        if rank_value is not None:
            score += max(0.0, 15.0 - float(rank_value))
        candidates.append(
            {
                "candidate_type": "prop",
                "sport": _safe_text(sport.get("name"), "MLB"),
                "sport_slug": "mlb",
                "surface_key": "pregame",
                "surface_title": "Top props artifact",
                "name": f"{player_name} {selection_label} {line_value:.1f} {market_label}" if line_value is not None else f"{player_name} {selection_label} {market_label}",
                "market": f"Pitcher {market_label}" if _safe_text(row.get("group"), "").lower() == "pitcher" else market_label,
                "market_key": market_key,
                "pick": pick,
                "matchup": matchup,
                "team": _safe_text(row.get("team"), "-"),
                "team_key": _normalized_market_text(_safe_text(row.get("team"), "")) or None,
                "player_team": _safe_text(row.get("team"), "-"),
                "line": f"{line_value:.1f}" if line_value is not None else "-",
                "odds": odds_text or "-",
                "projected": projected_text,
                "confidence": confidence_text,
                "edge": edge_text,
                "score": score,
                "href": f"/mlb/cards?date={selected_date}",
                "href_label": "Open board",
                "writeup": ". ".join(detail_bits) if detail_bits else f"Artifact-backed {market_label.lower()} view for {player_name}.",
                "display_pills": [
                    pill
                    for pill in (
                        f"Proj {projected_text}" if projected_text != "-" else "",
                        f"Line {line_value:.1f}" if line_value is not None else "",
                        f"Sim% {confidence_text}" if confidence_text != "-" else "",
                    )
                    if pill
                ],
                "owner_id": _safe_int(row.get("ownerId")),
                "selection_direction": selection_direction,
            }
        )
    return candidates


def _game_candidates_for_sport(sport: dict[str, Any]) -> list[dict[str, Any]]:
    dashboard_games = sport.get("dashboard_games") if isinstance(sport.get("dashboard_games"), list) else []
    candidates: list[dict[str, Any]] = []
    for game in dashboard_games:
        if not isinstance(game, dict):
            continue
        for row in _game_bet_candidates_from_game(sport, game, fallback_epoch=0.0):
            if not isinstance(row, dict):
                continue
            row = dict(row)
            row["candidate_type"] = "game"
            candidates.append(row)
    return candidates


def _candidate_is_final(candidate: dict[str, Any]) -> bool:
    if bool(candidate.get("is_final")):
        return True
    terminal_text = " ".join(
        _safe_text(candidate.get(field), "")
        for field in ("status_badge", "status_line", "status_display", "status_context", "detail", "summary", "score_kind")
    ).lower()
    return any(token in terminal_text for token in ("final", "game over", "completed"))


def _candidate_market_focuses(candidate: dict[str, Any]) -> set[str]:
    market_text = " ".join(
        [
            _safe_text(candidate.get("market"), ""),
            _safe_text(candidate.get("name"), ""),
            _safe_text(candidate.get("pick"), ""),
        ]
    )
    focuses: set[str] = set()
    explicit_market_key = _safe_text(candidate.get("market_key"), "").lower()
    if explicit_market_key:
        focuses.add(explicit_market_key)
    for key, aliases in _MARKET_FOCUS_ALIASES.items():
        if any(_text_has_market_alias(market_text, alias) for alias in aliases):
            focuses.add(key)
    fallback_market = _market_key_from_text(candidate.get("market"), allow_fallback=True)
    if fallback_market:
        focuses.add(fallback_market)
    return focuses


def _candidate_market_aliases(candidate: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    market_text = _safe_text(candidate.get("market"), "")
    normalized_market = _normalized_market_text(market_text)
    if normalized_market:
        aliases.add(normalized_market)
    for key in _candidate_market_focuses(candidate):
        aliases.add(_normalized_market_text(_market_label(key)))
        for alias in _MARKET_FOCUS_ALIASES.get(key, ()): 
            aliases.add(_normalized_market_text(alias))
    return {alias for alias in aliases if alias and alias not in _MARKET_FALLBACK_STOPWORDS}


def _resolved_requested_markets(
    question: str,
    candidates: list[dict[str, Any]],
    requested_markets: list[str] | tuple[str, ...] | None,
) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for item in requested_markets or []:
        key = str(item or "").strip().lower()
        if key and key not in seen:
            resolved.append(key)
            seen.add(key)

    normalized_question = _normalized_market_text(question)
    if not normalized_question:
        return resolved

    padded_question = f" {normalized_question} "
    for candidate in candidates:
        candidate_keys = sorted(_candidate_market_focuses(candidate))
        if not candidate_keys:
            continue
        aliases = _candidate_market_aliases(candidate)
        if not aliases:
            continue
        if not any(f" {alias} " in padded_question for alias in aliases):
            continue
        for key in candidate_keys:
            if key not in seen:
                resolved.append(key)
                seen.add(key)
    if "total_bases" in seen and "total" in seen:
        resolved = [key for key in resolved if key != "total"]
    return resolved


def _filter_candidates_to_requested_markets(
    candidates: list[dict[str, Any]],
    requested_markets: list[str] | tuple[str, ...] | None,
) -> list[dict[str, Any]]:
    requested_market_set = {str(item).strip().lower() for item in (requested_markets or []) if str(item).strip()}
    if not requested_market_set:
        return list(candidates)
    return [row for row in candidates if _candidate_market_focuses(row) & requested_market_set]


def _preferred_market_focus(candidate: dict[str, Any], preferences: dict[str, Any]) -> str | None:
    candidate_focuses = _candidate_market_focuses(candidate)
    if not candidate_focuses:
        return None
    requested_markets = [str(item).strip().lower() for item in (preferences.get("requested_markets") or []) if str(item).strip()]
    for key in requested_markets:
        if key in candidate_focuses:
            return key
    return sorted(candidate_focuses)[0] if candidate_focuses else None


def _candidate_selection_direction(candidate: dict[str, Any]) -> int:
    selection_text = _normalized_market_text(
        " ".join(
            [
                _safe_text(candidate.get("pick"), ""),
                _safe_text(candidate.get("name"), ""),
            ]
        )
    )
    if " under " in f" {selection_text} ":
        return -1
    if " over " in f" {selection_text} ":
        return 1
    return 0


def _candidate_subject_key(candidate: dict[str, Any]) -> str | None:
    if _safe_text(candidate.get("candidate_type"), "candidate") != "prop":
        return None
    name_text = _normalized_market_text(_safe_text(candidate.get("name"), ""))
    if not name_text:
        return None
    for marker in (" over ", " under "):
        if marker in f" {name_text} ":
            subject = name_text.split(marker, 1)[0].strip()
            return subject or None
    pick_text = _normalized_market_text(_safe_text(candidate.get("pick"), ""))
    if pick_text and name_text.endswith(pick_text):
        subject = name_text[: -len(pick_text)].strip()
        if subject:
            return subject
    return None


def _candidate_subject_aliases(candidate: dict[str, Any]) -> set[str]:
    subject_key = _candidate_subject_key(candidate)
    if not subject_key:
        return set()
    aliases = {subject_key}
    parts = [part for part in subject_key.split() if part]
    if len(parts) >= 2:
        aliases.add(parts[-1])
    if len(parts) >= 3:
        aliases.add(" ".join(parts[-2:]))
    return {alias for alias in aliases if len(alias) >= 3}


def _resolved_requested_subjects(question: str, candidates: list[dict[str, Any]]) -> list[str]:
    normalized_question = _normalized_market_text(question)
    if not normalized_question:
        return []
    matches: list[tuple[int, str]] = []
    seen: set[str] = set()
    question_tokens = normalized_question.split()

    def fuzzy_subject_position(aliases: set[str]) -> int | None:
        best_position: int | None = None
        best_score = 0.0
        for alias in aliases:
            alias_tokens = alias.split()
            if len(alias_tokens) < 2:
                continue
            window_size = len(alias_tokens)
            for index in range(0, len(question_tokens) - window_size + 1):
                window_text = " ".join(question_tokens[index : index + window_size])
                score = SequenceMatcher(None, window_text, alias).ratio()
                if score >= 0.88 and score > best_score:
                    best_score = score
                    best_position = index
        return best_position

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        subject_key = _candidate_subject_key(candidate)
        if not subject_key or subject_key in seen:
            continue
        for alias in sorted(_candidate_subject_aliases(candidate), key=len, reverse=True):
            match = re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalized_question)
            if not match:
                continue
            seen.add(subject_key)
            matches.append((match.start(), subject_key))
            break
        if subject_key in seen:
            continue
        fuzzy_position = fuzzy_subject_position(_candidate_subject_aliases(candidate))
        if fuzzy_position is not None:
            seen.add(subject_key)
            matches.append((fuzzy_position, subject_key))
    return [subject for _, subject in sorted(matches, key=lambda item: item[0])]


def _filter_candidates_to_requested_subjects(
    candidates: list[dict[str, Any]],
    requested_subjects: list[str] | tuple[str, ...] | None,
) -> list[dict[str, Any]]:
    wanted = {str(item).strip().lower() for item in (requested_subjects or []) if str(item).strip()}
    if not wanted:
        return candidates
    filtered = [candidate for candidate in candidates if (_candidate_subject_key(candidate) or "") in wanted]
    return filtered or candidates


def _candidate_team_key(candidate: dict[str, Any]) -> str | None:
    for field in ("team_key", "team", "team_abbr", "team_slug", "player_team"):
        value = _normalized_market_text(_safe_text(candidate.get(field), ""))
        if value:
            return value
    return None


def _candidate_market_margin(candidate: dict[str, Any]) -> tuple[float | None, float | None]:
    live_projection = _numeric_hint(candidate.get("live_projection"))
    projected_value = live_projection if live_projection is not None else _numeric_hint(candidate.get("projected"))
    line_value = _numeric_hint(candidate.get("line"))
    if projected_value is None or line_value is None:
        return (None, None)
    direction = _candidate_selection_direction(candidate)
    margin = projected_value - line_value
    if direction < 0:
        margin *= -1.0
    elif direction == 0:
        margin = abs(margin)
    scale_base = max(abs(line_value), 1.0)
    return (margin, margin / scale_base)


def _candidate_market_fit(candidate: dict[str, Any], market_context: dict[str, Any]) -> dict[str, Any]:
    market_keys = sorted(_candidate_market_focuses(candidate))
    market_key = market_keys[0] if market_keys else _market_key_from_text(candidate.get("market"), allow_fallback=True)
    candidate_type = _safe_text(candidate.get("candidate_type"), "candidate")
    sport_slug = _safe_text(candidate.get("sport_slug"), "").lower() or None
    profile = _market_shape_profile(market_key, candidate_type=candidate_type, sport_slug=sport_slug)
    margin, normalized_margin = _candidate_market_margin(candidate)
    price_edge_pct = market_context.get("price_edge_pct")
    confidence_pct = _pct_hint(candidate.get("confidence"))
    fit_score = 0.0
    note_parts: list[str] = []
    if margin is not None:
        fit_score += min(max(0.0, margin), float(profile["margin_cap"])) * float(profile["margin_weight"])
        note_parts.append(f"Projection gap {margin:+.2f} versus the current line")
    if normalized_margin is not None:
        fit_score += min(max(0.0, normalized_margin), float(profile["normalized_margin_cap"])) * float(profile["normalized_margin_weight"])
    if price_edge_pct is not None:
        fit_score += max(-5.0, min(6.0, float(price_edge_pct) * float(profile["price_edge_weight"])))
        note_parts.append(f"model-versus-price edge {float(price_edge_pct):+.2f} pts")
    else:
        edge_pct = _pct_hint(candidate.get("edge"))
        if edge_pct is not None:
            fit_score += max(-5.0, min(6.0, float(edge_pct) * float(profile["edge_weight"])))
            note_parts.append(f"stored edge {float(edge_pct):+.2f}%")
    if confidence_pct is not None:
        fit_score += max(
            -3.0,
            min(4.0, (float(confidence_pct) - float(profile["confidence_baseline"])) * float(profile["confidence_weight"])),
        )
    shape_note = str(profile.get("shape_detail") or profile["shape"]).replace("_", " ")
    note_parts.append(f"shape {shape_note}")
    return {
        "market_key": market_key,
        "market_label": _market_label(market_key),
        "market_shape": profile["shape"],
        "market_shape_detail": profile.get("shape_detail") or profile["shape"],
        "market_fit_score": round(fit_score, 2),
        "market_fit_note": "; ".join(note_parts) if note_parts else None,
    }


def _market_specific_score_adjustment(candidate: dict[str, Any], preferences: dict[str, Any], market_context: dict[str, Any]) -> float:
    requested_markets = [str(item).strip().lower() for item in (preferences.get("requested_markets") or []) if str(item).strip()]
    if not requested_markets:
        return 0.0
    focus = _preferred_market_focus(candidate, preferences)
    if focus is None:
        return 0.0
    margin, normalized_margin = _candidate_market_margin(candidate)
    candidate_type = _safe_text(candidate.get("candidate_type"), "candidate")
    sport_slug = _safe_text(candidate.get("sport_slug"), "").lower() or None
    profile = _market_shape_profile(focus, candidate_type=candidate_type, sport_slug=sport_slug)
    confidence_pct = _pct_hint(candidate.get("confidence")) or 0.0
    edge_pct = _pct_hint(candidate.get("edge"))
    if edge_pct is None:
        edge_pct = float(market_context.get("price_edge_pct") or 0.0)
    price_edge_pct = market_context.get("price_edge_pct")
    american_odds = market_context.get("american_odds")

    adjustment = 0.0
    if margin is not None:
        adjustment += min(max(0.0, margin), float(profile["margin_cap"])) * float(profile["margin_weight"])
    if normalized_margin is not None:
        adjustment += min(max(0.0, normalized_margin), float(profile["normalized_margin_cap"])) * float(profile["normalized_margin_weight"])
    if candidate_type == "game" and price_edge_pct is not None:
        adjustment += max(0.0, float(price_edge_pct)) * float(profile["price_edge_weight"])
    adjustment += max(0.0, float(edge_pct)) * float(profile["edge_weight"])
    adjustment += max(0.0, confidence_pct - float(profile["confidence_baseline"])) * float(profile["confidence_weight"])
    if candidate_type == "game" and preferences.get("live_only") and bool(candidate.get("is_live")):
        adjustment += 4.0
    if candidate_type != "game" and american_odds is not None and float(american_odds) >= 100.0 and float(price_edge_pct or 0.0) > 0.0:
        adjustment += float(profile["plus_money_bonus"])
    return round(adjustment, 3)


def _risk_profile_score_adjustment(candidate: dict[str, Any], preferences: dict[str, Any], market_context: dict[str, Any]) -> float:
    risk_profile = _safe_text(preferences.get("risk_profile"), "balanced").lower()
    if risk_profile not in {"conservative", "aggressive"}:
        return 0.0

    confidence_pct = _pct_hint(candidate.get("confidence")) or 0.0
    edge_pct = market_context.get("price_edge_pct")
    if edge_pct is None:
        edge_pct = _pct_hint(candidate.get("edge")) or 0.0
    american_odds = market_context.get("american_odds")
    market_key = _candidate_market_key(candidate)
    candidate_type = _safe_text(candidate.get("candidate_type"), "candidate")

    adjustment = 0.0
    if risk_profile == "conservative":
        adjustment += min(4.5, max(0.0, float(confidence_pct) - 54.0) * 0.24)
        adjustment += min(2.5, max(0.0, float(edge_pct)) * 0.14)
        if american_odds is not None and float(american_odds) >= 100.0:
            adjustment -= min(3.5, (float(american_odds) - 100.0) / 60.0)
        if candidate_type != "game" and market_key in _BINARY_CEILING_MARKETS:
            adjustment -= 1.75
        return round(adjustment, 3)

    if american_odds is not None and float(american_odds) >= 100.0:
        adjustment += min(4.5, (float(american_odds) - 100.0) / 55.0)
    elif american_odds is not None and float(american_odds) < 0.0:
        adjustment -= min(1.5, abs(float(american_odds)) / 220.0)
    adjustment += min(2.5, max(0.0, float(edge_pct)) * 0.16)
    if candidate_type != "game" and market_key in _BINARY_CEILING_MARKETS:
        adjustment += 1.75
    if confidence_pct > 0.0:
        adjustment -= min(1.5, max(0.0, 55.0 - float(confidence_pct)) * 0.04)
    return round(adjustment, 3)


def _candidate_market_key(candidate: dict[str, Any]) -> str | None:
    market_focuses = sorted(_candidate_market_focuses(candidate))
    if market_focuses:
        return market_focuses[0]
    combined = " ".join(
        [
            _safe_text(candidate.get("market"), ""),
            _safe_text(candidate.get("pick"), ""),
            _safe_text(candidate.get("name"), ""),
        ]
    )
    return _market_key_from_text(combined, allow_fallback=True)


def _candidate_matches_requested_markets(candidate: dict[str, Any], preferences: dict[str, Any]) -> bool:
    requested_markets = [str(key).strip().lower() for key in (preferences.get("requested_markets") or []) if str(key).strip()]
    if not requested_markets:
        return True
    return bool(_candidate_market_focuses(candidate) & set(requested_markets))


def _collect_candidates(overview: list[dict[str, Any]], preferences: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    wants_mlb_hr_targets = preferences.get("analysis_focus") == "mlb_home_runs" or "home_runs" in {
        str(item).strip().lower() for item in (preferences.get("requested_markets") or []) if str(item).strip()
    }
    for sport in overview:
        if not isinstance(sport, dict) or not _sport_matches_preferences(sport, preferences):
            continue
        home_rails = sport.get("home_rails") if isinstance(sport.get("home_rails"), dict) else {}
        if preferences.get("include_props"):
            if not preferences.get("live_only"):
                pregame = home_rails.get("pregame") if isinstance(home_rails.get("pregame"), dict) else {}
                for item in pregame.get("items") or []:
                    if isinstance(item, dict):
                        candidates.append(
                            _prop_candidate_from_item(
                                sport,
                                item,
                                surface_key="pregame",
                                surface_title=_safe_text(pregame.get("title"), "Pregame props"),
                            )
                        )
            if not preferences.get("pregame_only"):
                live = home_rails.get("live") if isinstance(home_rails.get("live"), dict) else {}
                for item in live.get("items") or []:
                    if isinstance(item, dict):
                        candidates.append(
                            _prop_candidate_from_item(
                                sport,
                                item,
                                surface_key="live",
                                surface_title=_safe_text(live.get("title"), "Top Live Props"),
                            )
                        )
        if preferences.get("include_games"):
            game_candidates = _game_candidates_for_sport(sport)
            if preferences.get("live_only"):
                game_candidates = [row for row in game_candidates if bool(row.get("is_live")) or "live" in _safe_text(row.get("market"), "").lower()]
            if preferences.get("pregame_only"):
                game_candidates = [row for row in game_candidates if not bool(row.get("is_live")) and "live" not in _safe_text(row.get("market"), "").lower()]
            candidates.extend(game_candidates)
        if wants_mlb_hr_targets and not preferences.get("live_only"):
            candidates.extend(_mlb_home_run_candidates_from_artifact(sport))

    candidates = [row for row in candidates if not _candidate_is_final(row)]
    candidates = _filter_candidates_to_requested_markets(candidates, preferences.get("requested_markets") or [])
    candidates = [
        row for row in candidates if _american_odds_match(_american_odds_value(row.get("odds")), preferences)
    ]

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in sorted(candidates, key=lambda candidate: float(candidate.get("score") or 0.0), reverse=True):
        identity = (
            _safe_text(row.get("candidate_type"), "candidate"),
            _safe_text(row.get("sport_slug"), "sport"),
            _safe_text(row.get("matchup"), "matchup"),
            _safe_text(row.get("market"), "market"),
            _safe_text(row.get("pick") or row.get("name"), "pick"),
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(row)
    return deduped


def _apply_advanced_context_to_candidates(
    candidates: list[dict[str, Any]],
    advanced_by_sport: dict[str, list[dict[str, Any]]],
    preferences: dict[str, Any],
) -> None:
    for candidate in candidates:
        sport_slug = _safe_text(candidate.get("sport_slug"), "sport").lower()
        advanced_context = advanced_by_sport.get(sport_slug, [])
        readiness_summary = _advanced_readiness_summary(advanced_context)
        market_context = _market_context(candidate)
        market_focuses = sorted(_candidate_market_focuses(candidate))
        market_fit = _candidate_market_fit(candidate, market_context)
        statcast_profile = _candidate_mlb_statcast_profile(candidate)
        candidate["advanced_context"] = advanced_context
        candidate["advanced_gate"] = readiness_summary
        candidate["market_context"] = market_context
        candidate["market_focuses"] = market_focuses
        candidate["market_fit"] = market_fit
        candidate["mlb_statcast_profile"] = statcast_profile
        candidate["advanced_signal_score"] = _candidate_advanced_signal_score(candidate)
        candidate["source_summary_score"] = _basketball_source_summary_score(candidate)
        candidate["score"] = (
            float(candidate.get("score") or 0.0)
            + _advanced_score_adjustment(readiness_summary)
            + _market_score_adjustment(market_context)
            + _market_specific_score_adjustment(candidate, preferences, market_context)
            + _risk_profile_score_adjustment(candidate, preferences, market_context)
            + float(candidate.get("advanced_signal_score") or 0.0)
            + float(candidate.get("source_summary_score") or 0.0)
        )


def _candidate_rationale(candidate: dict[str, Any]) -> str:
    advanced_context = candidate.get("advanced_context") if isinstance(candidate.get("advanced_context"), list) else []
    advanced_driver_text = _advanced_driver_text(advanced_context)
    advanced_gate = candidate.get("advanced_gate") if isinstance(candidate.get("advanced_gate"), dict) else {}
    market_context = candidate.get("market_context") if isinstance(candidate.get("market_context"), dict) else {}
    market_fit = candidate.get("market_fit") if isinstance(candidate.get("market_fit"), dict) else {}
    source_summary = (
        _safe_text(candidate.get("writeup"), "")
        or _safe_text(candidate.get("detail"), "")
        or _safe_text(candidate.get("summary"), "")
    )
    if _safe_text(candidate.get("candidate_type"), "") == "game":
        notes: list[str] = []
        if source_summary:
            notes.append(source_summary if source_summary.endswith(".") else f"{source_summary}.")
        if _safe_text(candidate.get("edge"), "-") != "-":
            notes.append(f"Model edge is {candidate.get('edge')} against the current book price.")
        if _safe_text(candidate.get("confidence"), "-") != "-":
            notes.append(f"Win-rate confidence sits at {candidate.get('confidence')}.")
        if _safe_text(candidate.get("odds"), "-") != "-":
            notes.append(f"The quoted book number is {candidate.get('odds')} on {candidate.get('pick')}.")
        if market_context.get("implied_probability") is not None:
            notes.append(f"Market implied probability is {market_context.get('implied_probability')}%.")
        if market_context.get("price_edge_pct") is not None:
            notes.append(f"Model versus price edge is {market_context.get('price_edge_pct')} points.")
        if advanced_driver_text:
            notes.append(f"Advanced drivers in play: {advanced_driver_text}.")
        missing_inputs = advanced_gate.get("missing_inputs") if isinstance(advanced_gate.get("missing_inputs"), list) else []
        if missing_inputs:
            notes.append(f"Readiness is partial because {len(missing_inputs)} advanced inputs are missing or unpublished.")
        return " ".join(notes) or "The game board shows a playable sportsbook edge with support from the current model snapshot."

    notes = []
    if source_summary:
        notes.append(source_summary if source_summary.endswith(".") else f"{source_summary}.")
    if _safe_text(candidate.get("projected"), "-") != "-" and _safe_text(candidate.get("line"), "-") != "-":
        notes.append(f"Model projection is {candidate.get('projected')} versus a book line of {candidate.get('line')}.")
    if bool(candidate.get("is_live")) and _safe_text(candidate.get("live_projection"), "-") != "-":
        actual_value = _safe_text(candidate.get("actual"), "-")
        notes.append(f"Live rest-of-game projection is {candidate.get('live_projection')} with current box score at {actual_value}.")
    if _safe_text(candidate.get("edge"), "-") != "-":
        notes.append(f"The stored edge reads {candidate.get('edge')}.")
    if _safe_text(candidate.get("confidence"), "-") != "-":
        notes.append(f"Sim confidence is {candidate.get('confidence')}.")
    if market_context.get("implied_probability") is not None:
        notes.append(f"Market implied probability is {market_context.get('implied_probability')}%.")
    if market_context.get("price_edge_pct") is not None:
        notes.append(f"Model versus price edge is {market_context.get('price_edge_pct')} points.")
    if _safe_text(market_fit.get("market_fit_note"), ""):
        notes.append(f"Market fit: {market_fit.get('market_fit_note')}.")
    if _safe_text(candidate.get("live_total"), "-") != "-":
        notes.append(f"Game context currently points to a live total of {candidate.get('live_total')}.")
    if advanced_driver_text:
        notes.append(f"Advanced drivers in play: {advanced_driver_text}.")
    signal_text = _advanced_signal_text(candidate)
    if signal_text:
        notes.append(f"Candidate-level advanced signals: {signal_text}.")
    statcast_text = _mlb_statcast_profile_text(candidate.get("mlb_statcast_profile") if isinstance(candidate.get("mlb_statcast_profile"), dict) else None)
    if statcast_text:
        notes.append(f"Raw Statcast context: {statcast_text}.")
    missing_inputs = advanced_gate.get("missing_inputs") if isinstance(advanced_gate.get("missing_inputs"), list) else []
    if missing_inputs:
        notes.append(f"Readiness is partial because {len(missing_inputs)} advanced inputs are missing or unpublished.")
    return " ".join(notes) or "The prop sits above the local model threshold with enough context to justify a sportsbook-facing recommendation."


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    market_context = candidate.get("market_context") if isinstance(candidate.get("market_context"), dict) else {}
    market_fit = candidate.get("market_fit") if isinstance(candidate.get("market_fit"), dict) else {}
    market_key = _candidate_market_key(candidate)
    output = {
        "candidate_type": _safe_text(candidate.get("candidate_type"), "candidate"),
        "sport": _safe_text(candidate.get("sport"), "Sport"),
        "sport_slug": _safe_text(candidate.get("sport_slug"), "sport"),
        "matchup": _safe_text(candidate.get("matchup"), "-"),
        "market": _safe_text(candidate.get("market"), "Market"),
        "market_key": market_fit.get("market_key") or market_key,
        "market_label": market_fit.get("market_label"),
        "market_shape": market_fit.get("market_shape"),
        "market_fit_score": market_fit.get("market_fit_score"),
        "market_fit_note": market_fit.get("market_fit_note"),
        "pick": _safe_text(candidate.get("pick"), _safe_text(candidate.get("name"), "Play")),
        "name": _safe_text(candidate.get("name"), _safe_text(candidate.get("pick"), "Play")),
        "surface": _safe_text(candidate.get("surface_title"), _safe_text(candidate.get("surface"), "Board")),
        "is_live": bool(candidate.get("is_live")),
        "line": _safe_text(candidate.get("line"), "-"),
        "odds": _safe_text(candidate.get("odds"), "-"),
        "american_odds": market_context.get("american_odds"),
        "decimal_odds": market_context.get("decimal_odds"),
        "implied_probability": market_context.get("implied_probability"),
        "model_probability": market_context.get("model_probability"),
        "price_edge_pct": market_context.get("price_edge_pct"),
        "edge": _safe_text(candidate.get("edge"), "-"),
        "confidence": _safe_text(candidate.get("confidence"), "-"),
        "projected": _safe_text(candidate.get("projected"), "-"),
        "live_projection": _safe_text(candidate.get("live_projection"), "-"),
        "actual": _safe_text(candidate.get("actual"), "-"),
        "href": candidate.get("href"),
        "href_label": _safe_text(candidate.get("href_label"), "Open board"),
        "rationale": _candidate_rationale(candidate),
        "score": round(float(candidate.get("score") or 0.0), 2),
        "advanced_ready": bool((candidate.get("advanced_gate") or {}).get("ready")),
        "advanced_readiness": _readiness_label(candidate.get("advanced_gate") or {}),
        "missing_advanced_inputs": [
            {
                "label": _safe_text(item.get("label"), "Advanced input"),
                "path": _safe_text(item.get("path"), "-"),
                "missing_reason": _safe_text(item.get("missing_reason"), "missing"),
            }
            for item in ((candidate.get("advanced_gate") or {}).get("missing_inputs") or [])[:3]
            if isinstance(item, dict)
        ],
        "advanced_inputs": [
            {
                "label": _safe_text(item.get("label"), "Advanced input"),
                "metrics": [str(metric).strip() for metric in (item.get("metrics") or []) if str(metric).strip()][:5],
            }
            for item in (candidate.get("advanced_context") or [])[:2]
            if isinstance(item, dict)
        ],
        "advanced_signals": [
            {
                "key": _safe_text(item.get("key"), "signal"),
                "label": _safe_text(item.get("label"), "Advanced signal"),
                "value": item.get("value"),
            }
            for item in (candidate.get("advanced_signals") or [])[:6]
            if isinstance(item, dict)
        ],
        "advanced_signal_score": round(float(candidate.get("advanced_signal_score") or 0.0), 2),
        "source_summary_score": round(float(candidate.get("source_summary_score") or 0.0), 2),
        "selection_direction": _candidate_selection_direction(candidate),
        "subject_key": _candidate_subject_key(candidate),
        "team_key": _candidate_team_key(candidate),
        "mlb_statcast_profile": candidate.get("mlb_statcast_profile") if isinstance(candidate.get("mlb_statcast_profile"), dict) else None,
    }
    pills = candidate.get("display_pills") if isinstance(candidate.get("display_pills"), list) else []
    output["display_pills"] = [str(item).strip() for item in pills if str(item).strip()][:6]
    return output


def _supporting_evidence_table(analysis_views: dict[str, Any]) -> dict[str, Any] | None:
    table = analysis_views.get("table") if isinstance(analysis_views.get("table"), dict) else {}
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    if not rows:
        return None
    evidence_rows: list[dict[str, Any]] = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        evidence_rows.append(
            {
                "target": _safe_text(row.get("label") or row.get("player") or row.get("name"), "Target"),
                "matchup": _safe_text(row.get("matchup"), "-"),
                "market": _safe_text(row.get("market"), "Market"),
                "pick": _safe_text(row.get("pick"), "-"),
                "score": row.get("score"),
                "why": _safe_text(row.get("why"), "-"),
            }
        )
    if not evidence_rows:
        return None
    return {
        "kind": "table",
        "title": _safe_text(table.get("title"), "Evidence grid"),
        "columns": ["target", "matchup", "market", "pick", "score", "why"],
        "rows": evidence_rows,
    }


def _recent_form_supporting_evidence_table(analysis_views: dict[str, Any]) -> dict[str, Any] | None:
    focus = _safe_text(analysis_views.get("focus"), "").lower()
    if focus not in {"nba_matchups", "wnba_matchups", "ncaab_matchups"}:
        return None
    table = analysis_views.get("table") if isinstance(analysis_views.get("table"), dict) else {}
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    if not rows:
        return None
    recent_form_rows: list[dict[str, Any]] = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        if all(
            row.get(key) in {None, ""}
            for key in [
                "last5_average",
                "last10_average",
                "last_game_value",
                "projected_minutes",
                "last10_workload",
                "last5_delta_signal",
                "last10_delta_signal",
                "last_game_delta_signal",
                "workload_delta_signal",
            ]
        ):
            continue
        recent_form_rows.append(
            {
                "target": _safe_text(row.get("label") or row.get("player") or row.get("name"), "Target"),
                "market": _safe_text(row.get("market"), "Market"),
                "last5_average": row.get("last5_average"),
                "last10_average": row.get("last10_average"),
                "last_game_value": row.get("last_game_value"),
                "projected_minutes": row.get("projected_minutes"),
                "last10_workload": row.get("last10_workload"),
                "last5_delta_signal": row.get("last5_delta_signal"),
                "last10_delta_signal": row.get("last10_delta_signal"),
                "last_game_delta_signal": row.get("last_game_delta_signal"),
                "workload_delta_signal": row.get("workload_delta_signal"),
                "why": _safe_text(row.get("why"), "-"),
            }
        )
    if not recent_form_rows:
        return None
    return {
        "kind": "table",
        "title": "Recent form table",
        "columns": ["target", "market", "last5_average", "last10_average", "last_game_value", "projected_minutes", "last10_workload", "last5_delta_signal", "last10_delta_signal", "last_game_delta_signal", "workload_delta_signal", "why"],
        "rows": recent_form_rows,
    }


def _build_supporting_evidence(recommendations: list[dict[str, Any]], analysis_views: dict[str, Any] | None) -> dict[str, Any] | None:
    if not recommendations:
        return None

    top = recommendations[0] if isinstance(recommendations[0], dict) else {}
    sections: list[dict[str, Any]] = []

    metric_items = [
        {"label": "Projection", "value": top.get("projected")},
        {"label": "Line", "value": top.get("line")},
        {"label": "Live projection", "value": top.get("live_projection")},
        {"label": "Confidence", "value": top.get("confidence")},
        {"label": "Price edge", "value": f"{top.get('price_edge_pct')}%" if top.get("price_edge_pct") is not None else None},
        {"label": "Implied probability", "value": f"{top.get('implied_probability')}%" if top.get("implied_probability") is not None else None},
        {"label": "Market fit", "value": top.get("market_fit_score")},
        {"label": "Advanced signal score", "value": top.get("advanced_signal_score")},
        {"label": "Source summary score", "value": top.get("source_summary_score")},
    ]
    metric_items = [item for item in metric_items if item.get("value") not in {None, "", "-"}]
    if metric_items:
        sections.append({"kind": "metrics", "title": "Top case evidence", "items": metric_items})

    signal_items = [
        {"label": _safe_text(item.get("label"), "Advanced signal"), "value": item.get("value")}
        for item in (top.get("advanced_signals") or [])[:6]
        if isinstance(item, dict) and item.get("value") not in {None, ""}
    ]
    if not signal_items and isinstance(analysis_views, dict):
        chart = analysis_views.get("chart") if isinstance(analysis_views.get("chart"), dict) else {}
        chart_rows = chart.get("rows") if isinstance(chart.get("rows"), list) else []
        chart_series = chart.get("series") if isinstance(chart.get("series"), list) else []
        first_chart_row = chart_rows[0] if chart_rows and isinstance(chart_rows[0], dict) else {}
        signal_items = [
            {"label": _humanize_signal_key(key), "value": first_chart_row.get(key)}
            for key in chart_series[:6]
            if key not in {"score", "market_fit_score", "advanced_signal_score", "source_summary_score"} and first_chart_row.get(key) not in {None, ""}
        ]
    if signal_items:
        sections.append({"kind": "signals", "title": "Key advanced signals", "items": signal_items})

    source_items: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for recommendation in recommendations[:3]:
        if not isinstance(recommendation, dict):
            continue
        for item in (recommendation.get("advanced_inputs") or [])[:3]:
            if not isinstance(item, dict):
                continue
            label = _safe_text(item.get("label"), "Advanced input")
            if label in seen_sources:
                continue
            seen_sources.add(label)
            metrics = [str(metric).strip() for metric in (item.get("metrics") or []) if str(metric).strip()]
            source_items.append({"label": label, "detail": ", ".join(metrics[:5]) if metrics else None})
    if source_items:
        sections.append({"kind": "sources", "title": "Source inputs", "items": source_items})

    if isinstance(analysis_views, dict):
        recent_form_table = _recent_form_supporting_evidence_table(analysis_views)
        if recent_form_table is not None:
            sections.append(recent_form_table)
        evidence_table = _supporting_evidence_table(analysis_views)
        if evidence_table is not None:
            sections.append(evidence_table)

    if not sections:
        return None

    return {
        "title": "Supporting evidence",
        "focus": analysis_views.get("focus") if isinstance(analysis_views, dict) else None,
        "sections": sections,
    }


def _parlay_rationale(legs: list[dict[str, Any]]) -> str:
    live_count = sum(1 for leg in legs if bool(leg.get("is_live")))
    sports = sorted({_safe_text(leg.get("sport"), "Sport") for leg in legs})
    if live_count and live_count == len(legs):
        return "All legs are coming from live board prices, so the angle is to exploit book lag while the local model is already repricing the same states."
    if live_count:
        return "This mix pairs live board momentum with pregame value so you are not stacking the same timing risk on every leg."
    if len(sports) > 1:
        return "This parlay spreads risk across sports and board types instead of doubling down on one matchup or one feed."
    return "This parlay keeps the legs inside the highest-scoring local recommendations while avoiding duplicate market exposure."


def _parlay_identity(leg: dict[str, Any]) -> str:
    return f"{_safe_text(leg.get('sport_slug'), 'sport')}::{_safe_text(leg.get('pick'), 'pick')}::{_safe_text(leg.get('market'), 'market')}::{_safe_text(leg.get('matchup'), 'matchup')}"


def _parlay_leg_market_shape(leg: dict[str, Any]) -> str:
    return _runtime_parlay_leg_market_shape(
        leg,
        safe_text=_safe_text,
        market_shape_profile=_market_shape_profile,
        market_key_from_text=_market_key_from_text,
    )


def _parlay_leg_market_key(leg: dict[str, Any]) -> str:
    return _runtime_parlay_leg_market_key(
        leg,
        safe_text=_safe_text,
        market_key_from_text=_market_key_from_text,
    )


def _medium_correlation_pair_blocked(sport_slug: str, first_market_key: str, second_market_key: str) -> bool:
    normalized_sport = _safe_text(sport_slug, "").lower()
    normalized_pair = tuple(sorted((_safe_text(first_market_key, "general_market").lower(), _safe_text(second_market_key, "general_market").lower())))
    return (normalized_sport, normalized_pair) in _MEDIUM_CORRELATION_SPORT_MARKET_PAIR_BLOCKS


def _parlay_market_pair_penalty(sport_slug: str, first_market_key: str, second_market_key: str) -> float:
    normalized_sport = _safe_text(sport_slug, "").lower()
    normalized_pair = tuple(sorted((_safe_text(first_market_key, "general_market").lower(), _safe_text(second_market_key, "general_market").lower())))
    return float(_PARLAY_SPORT_MARKET_PAIR_PENALTIES.get((normalized_sport, normalized_pair), 0.0))


def _market_script_cluster(market_key: str) -> str | None:
    return _MARKET_SCRIPT_CLUSTERS.get(_safe_text(market_key, "general_market").lower())


def _parlay_script_cluster_pair_penalty(sport_slug: str, first_market_key: str, second_market_key: str) -> tuple[float, str | None]:
    normalized_sport = _safe_text(sport_slug, "").lower()
    first_cluster = _market_script_cluster(first_market_key)
    second_cluster = _market_script_cluster(second_market_key)
    if not first_cluster or not second_cluster:
        return 0.0, None
    cluster_pair = tuple(sorted((first_cluster, second_cluster)))
    penalty = _SCRIPT_CLUSTER_PAIR_FALLBACK_PENALTIES.get((normalized_sport, cluster_pair))
    if penalty is None:
        return 0.0, None
    cluster_label = first_cluster if first_cluster == second_cluster else f"{first_cluster}/{second_cluster}"
    return float(penalty), f"shared {cluster_label} script"


def _parlay_script_cluster_penalty_multiplier(first_leg: dict[str, Any], second_leg: dict[str, Any]) -> tuple[float, str | None]:
    first_team = _candidate_team_key(first_leg)
    second_team = _candidate_team_key(second_leg)
    first_subject = _candidate_subject_key(first_leg)
    second_subject = _candidate_subject_key(second_leg)
    if not (first_team and second_team and first_subject and second_subject and first_subject != second_subject):
        return 1.0, None
    sport_slug = _safe_text(first_leg.get("sport_slug"), "sport").lower()
    first_cluster = _market_script_cluster(_parlay_leg_market_key(first_leg))
    second_cluster = _market_script_cluster(_parlay_leg_market_key(second_leg))
    if not first_cluster or not second_cluster:
        return 1.0, None
    cluster_pair = tuple(sorted((first_cluster, second_cluster)))
    multiplier = _EXPLICIT_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS.get((sport_slug, cluster_pair))
    if multiplier is None:
        return 1.0, None
    cluster_label = first_cluster if first_cluster == second_cluster else f"{first_cluster}/{second_cluster}"
    return float(multiplier), f"shared {cluster_label} script"


def _parlay_leg_is_live(leg: dict[str, Any]) -> bool:
    if leg.get("is_live") is True:
        return True
    surface_title = _safe_text(leg.get("surface_title"), "").lower()
    return "live" in surface_title


def _parlay_pair_penalty_multiplier(first_leg: dict[str, Any], second_leg: dict[str, Any]) -> tuple[float, str | None]:
    first_live = _parlay_leg_is_live(first_leg)
    second_live = _parlay_leg_is_live(second_leg)
    if first_live and second_live:
        return _LIVE_PARLAY_PAIR_PENALTY_MULTIPLIER, "live"
    if first_live or second_live:
        return _MIXED_TIMING_PARLAY_PAIR_PENALTY_MULTIPLIER, "mixed timing"
    return 1.0, None


def _parlay_pair_direction_multiplier(first_leg: dict[str, Any], second_leg: dict[str, Any]) -> tuple[float, str | None]:
    first_direction = _candidate_selection_direction(first_leg)
    second_direction = _candidate_selection_direction(second_leg)
    if first_direction != 0 and second_direction != 0 and first_direction != second_direction:
        sport_slug = _safe_text(first_leg.get("sport_slug"), "sport").lower()
        first_cluster = _market_script_cluster(_parlay_leg_market_key(first_leg))
        second_cluster = _market_script_cluster(_parlay_leg_market_key(second_leg))
        if first_cluster and second_cluster:
            cluster_pair = tuple(sorted((first_cluster, second_cluster)))
            override = _SCRIPT_CLUSTER_OPPOSING_DIRECTION_MULTIPLIERS.get((sport_slug, cluster_pair))
            if override is not None:
                return float(override), "opposing directions"
        return _OPPOSING_DIRECTION_PARLAY_PAIR_PENALTY_MULTIPLIER, "opposing directions"
    return 1.0, None


def _parlay_pair_subject_multiplier(first_leg: dict[str, Any], second_leg: dict[str, Any]) -> tuple[float, str | None]:
    first_subject = _candidate_subject_key(first_leg)
    second_subject = _candidate_subject_key(second_leg)
    if first_subject and second_subject and first_subject != second_subject:
        return _DIFFERENT_SUBJECT_PARLAY_PAIR_PENALTY_MULTIPLIER, "different players"
    return 1.0, None


def _parlay_pair_team_multiplier(first_leg: dict[str, Any], second_leg: dict[str, Any]) -> tuple[float, str | None]:
    first_team = _candidate_team_key(first_leg)
    second_team = _candidate_team_key(second_leg)
    first_subject = _candidate_subject_key(first_leg)
    second_subject = _candidate_subject_key(second_leg)
    if first_team and second_team and first_subject and second_subject and first_subject != second_subject:
        sport_slug = _safe_text(first_leg.get("sport_slug"), "sport").lower()
        market_pair = tuple(sorted((_parlay_leg_market_key(first_leg), _parlay_leg_market_key(second_leg))))
        cluster_pair = tuple(sorted(filter(None, (_market_script_cluster(market_pair[0]), _market_script_cluster(market_pair[1])))))
        if first_team == second_team:
            override = _SAME_TEAM_SPORT_MARKET_PAIR_PENALTY_MULTIPLIERS.get((sport_slug, market_pair))
            if override is not None:
                return float(override), "same team"
            cluster_override = _SAME_TEAM_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS.get((sport_slug, cluster_pair))
            if cluster_override is not None:
                return float(cluster_override), "same team"
            return 1.0, None
        override = _OPPOSING_TEAM_SPORT_MARKET_PAIR_PENALTY_MULTIPLIERS.get((sport_slug, market_pair))
        if override is not None:
            return float(override), "opposing teams"
        cluster_override = _OPPOSING_TEAM_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS.get((sport_slug, cluster_pair))
        if cluster_override is not None:
            return float(cluster_override), "opposing teams"
        return _OPPOSING_TEAM_PARLAY_PAIR_PENALTY_MULTIPLIER, "opposing teams"
    return 1.0, None


def _format_pair_penalty_value(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _parlay_pair_feature_profile(
    first_leg: dict[str, Any],
    second_leg: dict[str, Any],
    *,
    penalty_source: str,
    script_context: str | None,
) -> dict[str, Any]:
    first_market_key = _parlay_leg_market_key(first_leg)
    second_market_key = _parlay_leg_market_key(second_leg)
    first_cluster = _market_script_cluster(first_market_key)
    second_cluster = _market_script_cluster(second_market_key)
    first_team = _candidate_team_key(first_leg)
    second_team = _candidate_team_key(second_leg)
    first_subject = _candidate_subject_key(first_leg)
    second_subject = _candidate_subject_key(second_leg)
    first_direction = _candidate_selection_direction(first_leg)
    second_direction = _candidate_selection_direction(second_leg)

    team_relationship = None
    if first_team and second_team:
        team_relationship = "same_team" if first_team == second_team else "opposing_teams"

    subject_relationship = None
    if first_subject and second_subject:
        subject_relationship = "same_player" if first_subject == second_subject else "different_players"

    direction_relationship = None
    if first_direction != 0 and second_direction != 0:
        direction_relationship = "same_direction" if first_direction == second_direction else "opposing_directions"

    cluster_pair = None
    if first_cluster and second_cluster:
        cluster_pair = [first_cluster, second_cluster]

    return {
        "penalty_source": penalty_source,
        "same_game": _safe_text(first_leg.get("matchup"), "") == _safe_text(second_leg.get("matchup"), ""),
        "team_relationship": team_relationship,
        "subject_relationship": subject_relationship,
        "direction_relationship": direction_relationship,
        "market_keys": [first_market_key, second_market_key],
        "script_cluster_pair": cluster_pair,
        "script_context": script_context,
    }


def _parlay_pair_penalty(legs: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> dict[str, Any]:
    return _runtime_parlay_pair_penalty(
        legs,
        safe_text=_safe_text,
        market_label=_market_label,
        candidate_team_key=_candidate_team_key,
        candidate_subject_key=_candidate_subject_key,
        candidate_selection_direction=_candidate_selection_direction,
        market_script_clusters=_MARKET_SCRIPT_CLUSTERS,
        pair_penalties=_PARLAY_SPORT_MARKET_PAIR_PENALTIES,
        script_cluster_pair_fallback_penalties=_SCRIPT_CLUSTER_PAIR_FALLBACK_PENALTIES,
        explicit_script_cluster_penalty_multipliers=_EXPLICIT_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS,
        script_cluster_opposing_direction_multipliers=_SCRIPT_CLUSTER_OPPOSING_DIRECTION_MULTIPLIERS,
        same_team_sport_market_pair_penalty_multipliers=_SAME_TEAM_SPORT_MARKET_PAIR_PENALTY_MULTIPLIERS,
        same_team_script_cluster_penalty_multipliers=_SAME_TEAM_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS,
        opposing_team_sport_market_pair_penalty_multipliers=_OPPOSING_TEAM_SPORT_MARKET_PAIR_PENALTY_MULTIPLIERS,
        opposing_team_script_cluster_penalty_multipliers=_OPPOSING_TEAM_SCRIPT_CLUSTER_PENALTY_MULTIPLIERS,
        live_multiplier=_LIVE_PARLAY_PAIR_PENALTY_MULTIPLIER,
        mixed_timing_multiplier=_MIXED_TIMING_PARLAY_PAIR_PENALTY_MULTIPLIER,
        opposing_direction_multiplier=_OPPOSING_DIRECTION_PARLAY_PAIR_PENALTY_MULTIPLIER,
        different_subject_multiplier=_DIFFERENT_SUBJECT_PARLAY_PAIR_PENALTY_MULTIPLIER,
        opposing_team_multiplier=_OPPOSING_TEAM_PARLAY_PAIR_PENALTY_MULTIPLIER,
        parlay_leg_market_key_fn=_parlay_leg_market_key,
    )


def _medium_correlation_shape_limit(shape: str, sport_slug: str | None = None, market_key: str | None = None) -> int:
    sport_key = _safe_text(sport_slug, "").lower()
    market_key_value = _safe_text(market_key, "").lower()
    normalized = _safe_text(shape, "general_market") or "general_market"
    if sport_key and market_key_value:
        market_override = _MEDIUM_CORRELATION_SPORT_MARKET_LIMITS.get((sport_key, market_key_value))
        if market_override is not None:
            return int(market_override)
    if sport_key:
        override = _MEDIUM_CORRELATION_SPORT_SHAPE_LIMITS.get((sport_key, normalized))
        if override is not None:
            return int(override)
    return int(_MEDIUM_CORRELATION_SHAPE_LIMITS.get(normalized, _MEDIUM_CORRELATION_SHAPE_LIMITS["general_market"]))


def _parlay_type_label(parlay_type: str | None) -> str:
    value = _safe_text(parlay_type, "standard")
    return {
        "same_game": "same-game",
        "round_robin": "round robin",
    }.get(value, "standard")


def _parlay_label(legs: tuple[dict[str, Any], ...], preferences: dict[str, Any], *, round_robin: bool = False, ticket_index: int | None = None, ticket_total: int | None = None) -> str:
    leg_count = len(legs)
    if round_robin:
        unit = preferences.get("round_robin_unit") or leg_count
        sequence = f" ({ticket_index}/{ticket_total})" if ticket_index is not None and ticket_total is not None else ""
        return f"Round robin {unit}-leg ticket{sequence}"
    if preferences.get("parlay_type") == "same_game":
        return f"{leg_count}-leg same-game parlay"
    if preferences.get("cross_sport_required"):
        return f"{leg_count}-leg cross-sport parlay"
    return f"{leg_count}-leg {'live' if any(leg.get('is_live') for leg in legs) else 'pregame'} parlay"


def _risk_profile_stake_fraction(preferences: dict[str, Any]) -> float:
    risk_profile = _safe_text(preferences.get("risk_profile"), "balanced")
    if risk_profile == "conservative":
        return 0.02
    if risk_profile == "aggressive":
        return 0.06
    return 0.04


def _parlay_stake_plan(preferences: dict[str, Any], *, ticket_total: int | None = None) -> dict[str, Any]:
    bankroll_amount = preferences.get("bankroll_amount")
    max_exposure_pct = preferences.get("max_exposure_pct")
    max_exposure_amount = preferences.get("max_exposure_amount")
    bankroll_value = float(bankroll_amount) if bankroll_amount is not None else None
    pct_cap_amount = None
    if bankroll_value is not None and max_exposure_pct is not None:
        pct_cap_amount = round(bankroll_value * (float(max_exposure_pct) / 100.0), 2)

    effective_cap = None
    cap_source = None
    explicit_caps = [
        value
        for value in (pct_cap_amount, float(max_exposure_amount) if max_exposure_amount is not None else None)
        if value is not None
    ]
    if explicit_caps:
        effective_cap = round(min(explicit_caps), 2)
        cap_source = "requested_exposure_cap"
    elif bankroll_value is not None:
        effective_cap = round(bankroll_value * _risk_profile_stake_fraction(preferences), 2)
        cap_source = "risk_profile_bankroll"

    suggested_stake = effective_cap
    if effective_cap is not None and ticket_total and ticket_total > 1:
        suggested_stake = round(effective_cap / float(ticket_total), 2)

    stake_note = None
    if effective_cap is not None and ticket_total and ticket_total > 1:
        stake_note = f"Suggested stake ${suggested_stake:.2f} per ticket keeps the full set within a ${effective_cap:.2f} exposure cap."
    elif effective_cap is not None and cap_source == "requested_exposure_cap":
        stake_note = f"Suggested stake ${effective_cap:.2f} respects the requested exposure cap."
    elif effective_cap is not None and cap_source == "risk_profile_bankroll":
        stake_note = f"Suggested stake ${effective_cap:.2f} comes from the stated bankroll and {_safe_text(preferences.get('risk_profile'), 'balanced')} risk profile."

    return {
        "suggested_stake": suggested_stake,
        "suggested_total_exposure": effective_cap,
        "exposure_cap_amount": effective_cap,
        "exposure_cap_source": cap_source,
        "stake_note": stake_note,
    }


def _has_tight_exposure_cap(preferences: dict[str, Any]) -> bool:
    max_exposure_pct = preferences.get("max_exposure_pct")
    if max_exposure_pct is not None and float(max_exposure_pct) <= 5.0:
        return True
    bankroll_amount = preferences.get("bankroll_amount")
    max_exposure_amount = preferences.get("max_exposure_amount")
    if bankroll_amount is None or max_exposure_amount is None:
        return False
    try:
        bankroll_value = float(bankroll_amount)
        exposure_value = float(max_exposure_amount)
    except Exception:
        return False
    if bankroll_value <= 0.0:
        return False
    return (exposure_value / bankroll_value) <= 0.05


def _parlay_matches_preferences(legs: tuple[dict[str, Any], ...], preferences: dict[str, Any]) -> bool:
    return _runtime_parlay_matches_preferences(
        legs,
        preferences,
        safe_text=_safe_text,
        sport_market_pair_blocks=_MEDIUM_CORRELATION_SPORT_MARKET_PAIR_BLOCKS,
        medium_correlation_shape_limits=_MEDIUM_CORRELATION_SHAPE_LIMITS,
        medium_correlation_sport_shape_limits=_MEDIUM_CORRELATION_SPORT_SHAPE_LIMITS,
        medium_correlation_sport_market_limits=_MEDIUM_CORRELATION_SPORT_MARKET_LIMITS,
        parlay_leg_market_shape_fn=_parlay_leg_market_shape,
        parlay_leg_market_key_fn=_parlay_leg_market_key,
    )


def _build_parlay_payload(legs: tuple[dict[str, Any], ...], preferences: dict[str, Any], *, round_robin: bool = False, ticket_index: int | None = None, ticket_total: int | None = None, anchor_legs: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    return _runtime_build_parlay_payload(
        legs,
        preferences,
        round_robin=round_robin,
        ticket_index=ticket_index,
        ticket_total=ticket_total,
        anchor_legs=anchor_legs,
        candidate_summary=_candidate_summary,
        parlay_pair_penalty_fn=_parlay_pair_penalty,
        decimal_to_american=_decimal_to_american,
        american_odds_value=_american_odds_value,
        american_odds_match=_american_odds_match,
        safe_text=_safe_text,
        parlay_stake_plan=_parlay_stake_plan,
        parlay_rationale=_parlay_rationale,
        parlay_label=_parlay_label,
    )


def _parlay_rank_score(parlay: dict[str, Any], preferences: dict[str, Any]) -> float:
    parlay_with_numeric_odds = dict(parlay)
    parlay_with_numeric_odds["combined_odds"] = _american_odds_value(parlay.get("combined_odds")) or 0.0
    return _runtime_parlay_rank_score(parlay_with_numeric_odds, preferences)


def _build_round_robin_parlays(candidate_pool: list[dict[str, Any]], *, limit: int, preferences: dict[str, Any], min_leg_count: int, max_leg_count: int) -> list[dict[str, Any]]:
    return _runtime_build_round_robin_parlays(
        candidate_pool,
        limit=limit,
        preferences=preferences,
        max_leg_count=max_leg_count,
        has_tight_exposure_cap=_has_tight_exposure_cap,
        parlay_matches_preferences_fn=_parlay_matches_preferences,
        parlay_identity=_parlay_identity,
        build_parlay_payload_fn=_build_parlay_payload,
        candidate_summary=_candidate_summary,
        parlay_rank_score_fn=_parlay_rank_score,
    )


def _build_parlays(candidates: list[dict[str, Any]], *, limit: int, preferences: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return _runtime_build_parlays(
        candidates,
        limit=limit,
        preferences=preferences,
        safe_text=_safe_text,
        has_tight_exposure_cap=_has_tight_exposure_cap,
        parlay_matches_preferences_fn=_parlay_matches_preferences,
        parlay_identity=_parlay_identity,
        build_parlay_payload_fn=_build_parlay_payload,
        build_round_robin_parlays_fn=lambda candidate_pool, *, limit, preferences, max_leg_count: _build_round_robin_parlays(
            candidate_pool,
            limit=limit,
            preferences=preferences,
            min_leg_count=2,
            max_leg_count=max_leg_count,
        ),
        parlay_rank_score_fn=_parlay_rank_score,
    )


def _query_needs_mlb_home_run_candidates(preferences: dict[str, Any]) -> bool:
    requested_markets = {
        str(item).strip().lower()
        for item in (preferences.get("requested_markets") or [])
        if str(item).strip()
    }
    return preferences.get("analysis_focus") == "mlb_home_runs" or "home_runs" in requested_markets


def _has_mlb_home_run_candidates(candidates: list[dict[str, Any]]) -> bool:
    return any(
        _safe_text(candidate.get("sport_slug"), "").lower() == "mlb" and "home_runs" in _candidate_market_focuses(candidate)
        for candidate in candidates
    )


def run_intelligence_query(
    question: str,
    *,
    selected_date: str | None = None,
    mode: str | None = None,
    sport: str | None = None,
    limit: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    preferences = _query_preferences(question, mode=mode, sport=sport, limit=limit)
    effective_date = _effective_date(selected_date or preferences.get("requested_date"))
    overview = build_intelligence_overview(selected_date=effective_date, force_refresh=force_refresh)
    tracked = _tracked_repo_files()
    advanced_by_sport = {
        _safe_text(sport_row.get("slug"), "sport").lower(): _advanced_input_rows_for_sport(sport_row, tracked)
        for sport_row in overview
        if isinstance(sport_row, dict)
    }
    candidates = _collect_candidates(overview, preferences)
    if _query_needs_mlb_home_run_candidates(preferences) and not _has_mlb_home_run_candidates(candidates):
        for sport_row in overview:
            if not isinstance(sport_row, dict):
                continue
            if _safe_text(sport_row.get("slug"), "").lower() != "mlb":
                continue
            candidates.extend(_mlb_home_run_candidates_from_artifact(sport_row))
            break
    for sport_row in overview:
        if not isinstance(sport_row, dict):
            continue
        extra_subject_candidates = _mlb_subject_prop_candidates_from_artifact(
            sport_row,
            question=question,
            preferences=preferences,
        )
        for candidate in extra_subject_candidates:
            candidate_subject = _candidate_subject_key(candidate)
            candidate_market = _candidate_market_key(candidate)
            if any(
                _candidate_subject_key(existing) == candidate_subject
                and _candidate_market_key(existing) == candidate_market
                for existing in candidates
            ):
                continue
            candidates.append(candidate)
    resolved_requested_subjects = _resolved_requested_subjects(question, candidates)
    if resolved_requested_subjects != (preferences.get("requested_subjects") or []):
        preferences = {**preferences, "requested_subjects": resolved_requested_subjects}
        candidates = _filter_candidates_to_requested_subjects(candidates, resolved_requested_subjects)
    resolved_requested_markets = _resolved_requested_markets(question, candidates, preferences.get("requested_markets") or [])
    if resolved_requested_markets != (preferences.get("requested_markets") or []):
        preferences = {**preferences, "requested_markets": resolved_requested_markets}
        candidates = _filter_candidates_to_requested_markets(candidates, resolved_requested_markets)
    _apply_advanced_context_to_candidates(candidates, advanced_by_sport, preferences)
    candidates = sorted(candidates, key=lambda candidate: float(candidate.get("score") or 0.0), reverse=True)
    recommendations = [_candidate_summary(candidate) for candidate in candidates[: preferences["limit"]]]
    parlay_limit = preferences["limit"] if preferences.get("parlay_type") == "round_robin" else min(3, preferences["limit"])
    parlays = _build_parlays(candidates, limit=parlay_limit, preferences=preferences) if preferences.get("intent") == "parlay" or "parlay" in preferences.get("question", "").lower() else []
    analysis_views = _analysis_views_for_query(candidates, preferences)
    supporting_evidence = _build_supporting_evidence(recommendations, analysis_views)

    live_rows = sum(1 for candidate in candidates if bool(candidate.get("is_live")))
    pregame_rows = sum(1 for candidate in candidates if not bool(candidate.get("is_live")))
    data_notes = []
    for sport_row in overview:
        warnings = [str(item).strip() for item in (sport_row.get("data_warnings") or []) if str(item).strip()]
        if warnings:
            data_notes.append(f"{_safe_text(sport_row.get('name'), 'Sport')}: {'; '.join(warnings)}")
        sport_slug = _safe_text(sport_row.get("slug"), "sport").lower()
        advanced_rows = [row for row in advanced_by_sport.get(sport_slug, []) if bool(row.get("exists"))]
        advanced_driver_text = _advanced_driver_text(advanced_rows, limit_groups=1, limit_metrics=3)
        if advanced_driver_text:
            data_notes.append(f"{_safe_text(sport_row.get('name'), 'Sport')} advanced inputs: {advanced_driver_text}")
        readiness = _advanced_readiness_summary(advanced_by_sport.get(sport_slug, []))
        if readiness.get("missing_inputs"):
            missing_labels = ", ".join(item.get("label") or "input" for item in readiness.get("missing_inputs", [])[:3])
            data_notes.append(f"{_safe_text(sport_row.get('name'), 'Sport')} missing advanced inputs: {missing_labels}")

    readiness_gate = _build_readiness_gate(overview, tracked)

    headline = "The Syndicate brief"
    if preferences["intent"] == "parlay":
        headline = "The Syndicate parlay builder"
    elif preferences["intent"] == "live_bets":
        headline = "The Syndicate live board brief"
    elif preferences["intent"] == "pregame_bets":
        headline = "The Syndicate pregame board brief"
    elif preferences.get("comparison_requested") and len(preferences.get("requested_subjects") or []) >= 2:
        compared = [" ".join(part.capitalize() for part in str(subject).split()) for subject in (preferences.get("requested_subjects") or [])[:2]]
        headline = f"The Syndicate comparison: {compared[0]} vs {compared[1]}"
    elif preferences.get("requested_markets"):
        first_market = _market_label((preferences.get("requested_markets") or [None])[0]).lower()
        headline = f"The Syndicate {first_market} board"

    summary = (
        f"Scanned {len(candidates)} board candidates across {len([sport_row for sport_row in overview if _sport_matches_preferences(sport_row, preferences)]) or len(overview)} sports. "
        f"Live candidates: {live_rows}. Pregame candidates: {pregame_rows}."
    )

    return {
        "selected_date": effective_date,
        "preferences": preferences,
        "headline": headline,
        "summary": summary,
        "parsed_request": _parlay_request_summary(preferences),
        "recommendations": recommendations,
        "parlays": parlays,
        "analysis_views": analysis_views,
        "supporting_evidence": supporting_evidence,
        "board_notes": data_notes[:8],
        "readiness_gate": readiness_gate,
        "local_only": True,
    }