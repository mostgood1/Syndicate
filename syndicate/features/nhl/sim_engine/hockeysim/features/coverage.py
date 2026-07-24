"""Data-coverage audit for the hockeysim feature loaders.

The loaders (``loaders.py``) deliberately degrade gracefully — a missing ``team_xg`` file yields
league-average projections, absent lineups yield empty rosters, etc. That is the correct *runtime*
behavior (CLAUDE.md: "degraded/empty state, not on-request backfill"), but silent fallbacks hide
data gaps that materially change prediction quality. This module makes those gaps **explicit and
testable**: it reports, per game and per slate, which inputs are real vs. defaulted, and flags when
a projection is running *degraded* (no team xG -> league-average strength only).

This is the read-side "am I actually running on real data?" check. It never fetches anything — data
acquisition is a producer/worker concern (the Phase-5 producers + ingestion). It only observes what
the mirror currently provides so callers, telemetry, and the Phase-3 truth layer can trust or
distrust a slate before consuming it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import loaders


@dataclass(frozen=True)
class TeamDataCoverage:
    team: str
    abbrev: Optional[str]
    has_xg: bool
    lineup_players: int
    has_confirmed_goalie: bool

    @property
    def has_lineup(self) -> bool:
        return self.lineup_players > 0


@dataclass(frozen=True)
class GameDataCoverage:
    game_pk: str
    date: str
    home: TeamDataCoverage
    away: TeamDataCoverage
    has_market_lines: bool
    # True when either side lacks team xG, so the projection fell back to league-average strength.
    projection_degraded: bool
    missing: Tuple[str, ...]


@dataclass(frozen=True)
class SlateDataCoverage:
    date: str
    scoreboard_present: bool
    team_xg_available: bool
    games: Tuple[GameDataCoverage, ...]

    @property
    def game_count(self) -> int:
        return len(self.games)

    @property
    def degraded_games(self) -> int:
        return sum(1 for g in self.games if g.projection_degraded)

    @property
    def fully_covered_games(self) -> int:
        return sum(1 for g in self.games if not g.missing)

    def summary(self) -> Dict[str, object]:
        """Flat dict for logging / telemetry / the Phase-3 truth-layer gate."""
        return {
            "date": self.date,
            "scoreboard_present": self.scoreboard_present,
            "team_xg_available": self.team_xg_available,
            "games": self.game_count,
            "degraded_games": self.degraded_games,
            "fully_covered_games": self.fully_covered_games,
            "missing_by_game": {g.game_pk: list(g.missing) for g in self.games if g.missing},
        }


def _team_coverage(
    name: str,
    *,
    xg_map: Dict[str, Dict[str, float]],
    lineups: Dict[str, List[Dict[str, str]]],
    goalies: Dict[str, Dict[str, str]],
) -> TeamDataCoverage:
    ab = loaders._abbr(name)
    has_xg = bool(ab and ab in xg_map and xg_map[ab].get("xgf60") is not None)
    lineup_rows = lineups.get(ab or "", [])
    goalie_row = goalies.get(ab or "")
    confirmed = bool(goalie_row and str(goalie_row.get("goalie") or "").strip())
    return TeamDataCoverage(
        team=name,
        abbrev=ab,
        has_xg=has_xg,
        lineup_players=len(lineup_rows),
        has_confirmed_goalie=confirmed,
    )


def build_game_coverage(
    game_pk: str,
    date: str,
    home_name: str,
    away_name: str,
    *,
    root: Optional[Path] = None,
    xg_map: Optional[Dict[str, Dict[str, float]]] = None,
    lineups: Optional[Dict[str, List[Dict[str, str]]]] = None,
    goalies: Optional[Dict[str, Dict[str, str]]] = None,
    has_market_lines: bool = False,
) -> GameDataCoverage:
    """Report which real inputs back one game (shared maps may be passed by the slate builder)."""
    if xg_map is None:
        xg_map = loaders.load_team_xg_map(date, root=root)
    if lineups is None:
        lineups = loaders.load_lineups(date, root=root)
    if goalies is None:
        goalies = loaders.load_starting_goalies(date, root=root)

    home = _team_coverage(home_name, xg_map=xg_map, lineups=lineups, goalies=goalies)
    away = _team_coverage(away_name, xg_map=xg_map, lineups=lineups, goalies=goalies)

    missing: List[str] = []
    if not (home.has_xg and away.has_xg):
        missing.append("team_xg")
    if not (home.has_lineup and away.has_lineup):
        missing.append("lineups")
    if not (home.has_confirmed_goalie and away.has_confirmed_goalie):
        missing.append("starting_goalie")
    if not has_market_lines:
        missing.append("market_lines")

    degraded = not (home.has_xg and away.has_xg)
    return GameDataCoverage(
        game_pk=str(game_pk),
        date=str(date),
        home=home,
        away=away,
        has_market_lines=has_market_lines,
        projection_degraded=degraded,
        missing=tuple(missing),
    )


def build_slate_coverage(date: str, *, root: Optional[Path] = None) -> SlateDataCoverage:
    """Audit an entire date's scoreboard: how much of it is backed by real data?

    Reads each source once and reuses it across games (same discipline as ``build_slate_features``).
    Returns an empty-but-well-formed report when no scoreboard is mirrored.
    """
    games_meta = loaders._load_scoreboard_games(date, root=root)
    xg_map = loaders.load_team_xg_map(date, root=root)
    lineups = loaders.load_lineups(date, root=root)
    goalies = loaders.load_starting_goalies(date, root=root)

    game_reports: List[GameDataCoverage] = []
    for pk, home_name, away_name in games_meta:
        game_reports.append(
            build_game_coverage(
                pk, date, home_name, away_name,
                root=root, xg_map=xg_map, lineups=lineups, goalies=goalies,
                has_market_lines=False,  # market lines not wired into the loader yet (Phase 5)
            )
        )
    return SlateDataCoverage(
        date=str(date),
        scoreboard_present=bool(games_meta),
        team_xg_available=bool(xg_map),
        games=tuple(game_reports),
    )
