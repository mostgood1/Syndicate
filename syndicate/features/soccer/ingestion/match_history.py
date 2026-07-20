"""Team/league match-history ingestion from football-data.co.uk.

Free per-season CSVs with full-time/half-time scores, shots, shots on
target, corners, cards, and closing odds for the big-five European leagues
plus a "next tier" of leagues with the same column schema (Eredivisie,
Primeira Liga, Championship, Belgian Pro League). This is the SoccerSim
truth layer: normalized rows feed the calibration package's
``BenchmarkMatchRecord`` snapshots, and the closing odds columns double as
a market baseline for validation.

MLS is not covered by football-data.co.uk; its match history arrives with
the American Soccer Analysis player/team ingestion (see player_history.py).
"""

from __future__ import annotations

import io
from typing import Any

import pandas as pd
import requests

from syndicate.features.soccer.sim_engine.soccersim.calibration.benchmark_contracts import BenchmarkMatchRecord

LEAGUE_HISTORY_CODES: dict[str, str] = {
    "epl": "E0",
    "la_liga": "SP1",
    "bundesliga": "D1",
    "serie_a": "I1",
    "ligue_1": "F1",
    "eredivisie": "N1",
    "primeira_liga": "P1",
    "championship": "E1",
    "belgian_pro_league": "B1",
}

_BASE_URL = "https://www.football-data.co.uk/mmz4281"


def season_code(start_year: int) -> str:
    """football-data.co.uk season path: 2025-26 -> '2526'."""
    start = int(start_year) % 100
    end = (int(start_year) + 1) % 100
    return f"{start:02d}{end:02d}"


def fetch_match_history_csv(league: str, start_year: int, *, timeout: int = 30) -> str:
    code = LEAGUE_HISTORY_CODES[str(league).strip().lower()]
    url = f"{_BASE_URL}/{season_code(start_year)}/{code}.csv"
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (SyndicateSoccerSim)"})
    response.raise_for_status()
    return response.text


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == "":
            return None
        return int(float(value))
    except Exception:
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def normalize_match_history(csv_text: str, *, league: str, season: int) -> list[dict[str, Any]]:
    """Normalize a football-data.co.uk season CSV into SoccerSim history rows."""
    frame = pd.read_csv(io.StringIO(csv_text))
    rows: list[dict[str, Any]] = []
    for index, raw in frame.iterrows():
        home_team = str(raw.get("HomeTeam") or "").strip()
        away_team = str(raw.get("AwayTeam") or "").strip()
        home_goals = _safe_int(raw.get("FTHG"))
        away_goals = _safe_int(raw.get("FTAG"))
        if not home_team or not away_team or home_goals is None or away_goals is None:
            continue
        date = str(raw.get("Date") or "").strip()
        rows.append(
            {
                "league": league,
                "season": season,
                "match_id": f"{league}_{season}_{index}_{home_team}_{away_team}".replace(" ", "_").lower(),
                "date": date,
                "home_team": home_team,
                "away_team": away_team,
                "home_goals": home_goals,
                "away_goals": away_goals,
                "ht_home_goals": _safe_int(raw.get("HTHG")),
                "ht_away_goals": _safe_int(raw.get("HTAG")),
                "home_shots": _safe_int(raw.get("HS")),
                "away_shots": _safe_int(raw.get("AS")),
                "home_shots_on_target": _safe_int(raw.get("HST")),
                "away_shots_on_target": _safe_int(raw.get("AST")),
                "home_corners": _safe_int(raw.get("HC")),
                "away_corners": _safe_int(raw.get("AC")),
                "home_fouls": _safe_int(raw.get("HF")),
                "away_fouls": _safe_int(raw.get("AF")),
                "home_yellow_cards": _safe_int(raw.get("HY")),
                "away_yellow_cards": _safe_int(raw.get("AY")),
                "home_red_cards": _safe_int(raw.get("HR")),
                "away_red_cards": _safe_int(raw.get("AR")),
                "odds_home": _safe_float(raw.get("AvgH") if raw.get("AvgH") is not None else raw.get("B365H")),
                "odds_draw": _safe_float(raw.get("AvgD") if raw.get("AvgD") is not None else raw.get("B365D")),
                "odds_away": _safe_float(raw.get("AvgA") if raw.get("AvgA") is not None else raw.get("B365A")),
                "odds_over_2_5": _safe_float(raw.get("Avg>2.5") if raw.get("Avg>2.5") is not None else raw.get("B365>2.5")),
                "odds_under_2_5": _safe_float(raw.get("Avg<2.5") if raw.get("Avg<2.5") is not None else raw.get("B365<2.5")),
            }
        )
    return rows


def to_benchmark_match_records(rows: list[dict[str, Any]]) -> tuple[BenchmarkMatchRecord, ...]:
    records: list[BenchmarkMatchRecord] = []
    for row in rows:
        home_goals = _safe_int(row.get("home_goals")) or 0
        away_goals = _safe_int(row.get("away_goals")) or 0
        ht_home = _safe_int(row.get("ht_home_goals"))
        ht_away = _safe_int(row.get("ht_away_goals"))
        if ht_home is None or ht_away is None:
            half_home = (0, home_goals)
            half_away = (0, away_goals)
        else:
            half_home = (ht_home, home_goals - ht_home)
            half_away = (ht_away, away_goals - ht_away)
        shots = (_safe_int(row.get("home_shots")) or 0) + (_safe_int(row.get("away_shots")) or 0)
        shots_on_target = (_safe_int(row.get("home_shots_on_target")) or 0) + (_safe_int(row.get("away_shots_on_target")) or 0)
        corners = (_safe_int(row.get("home_corners")) or 0) + (_safe_int(row.get("away_corners")) or 0)
        records.append(
            BenchmarkMatchRecord(
                match_id=str(row.get("match_id") or ""),
                home_team=str(row.get("home_team") or ""),
                away_team=str(row.get("away_team") or ""),
                season=row.get("season"),
                home_goals=home_goals,
                away_goals=away_goals,
                half_home_goals=half_home,
                half_away_goals=half_away,
                possessions=0,
                shots=int(shots),
                shots_on_target=int(shots_on_target),
                corners=int(corners),
                metadata={
                    "league": row.get("league"),
                    "date": row.get("date"),
                    "odds_home": row.get("odds_home"),
                    "odds_draw": row.get("odds_draw"),
                    "odds_away": row.get("odds_away"),
                },
            )
        )
    return tuple(records)


__all__ = [
    "LEAGUE_HISTORY_CODES",
    "fetch_match_history_csv",
    "normalize_match_history",
    "season_code",
    "to_benchmark_match_records",
]
