"""NCAAB team-model inputs for the native live engine.

Phase P4 of `docs/ai_context/basketball_live_native_plan.md` (lane
`ncaab-native-live-tier`). The engine resumed under NCAAB rules needs, per
team, a points-per-possession expectation and a tempo; this module turns the
efficiency ratings tables written by `scripts/build_ncaab_team_ratings.py`
(adjusted O/D/tempo, `team_ratings_<season>_asof_<YYYYMMDD>.csv`, scheduled
daily 10:45Z by `local_production.SCHEDULED_JOBS`) into that game prior.

THREE RULES THIS MODULE KEEPS, each from a failure this repo has already had:

  * No leakage. The table used for a game is the newest whose `as_of` is
    STRICTLY BEFORE the game date. A table that already contains the game
    grades the model on its own answer.
  * Refuse by name; never default. A team with no rated row returns an
    `NcaabPriorRefusal("team_unrated", ...)` -- not a league-average team. A
    neutral default is indistinguishable from a working input at every level
    except the data (`model_engine_standard.md` section 0).
  * Season convention. The tables use ESPN's season year -- the year the season
    ENDS (2025-26 is 2026). `syndicate/features/ncaab/sources.season_for_date`
    uses the year it STARTS. `espn_season_for()` here is the tables' convention.

The prior, per game:
    possessions  = tempo_home * tempo_away / league_tempo
    ppp_side     = adj_off_side * adj_def_other / league_off / 100
    points_side  = ppp_side * possessions  +/- HOME_POINTS / 2 at a home site
League means are the table's own means: the producer shrinks every team toward
its league mean, so the table mean IS that mean to rounding. HOME_POINTS is the
producer's walk-forward fit (2.9 pts, 2025-26); it moves the margin and leaves
the total alone. `tests/test_ncaab_live_team_model.py` pins it to the producer.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Union

from syndicate.features.shared.source_roots import preferred_artifact_roots

HOME_POINTS = 2.9  # == scripts/build_ncaab_team_ratings.HOME_POINTS (walk-forward fit, 2025-26)
PRIOR_REGRESSION = 0.30  # == build_ncaab_team_ratings.PRIOR_REGRESSION: last season's table, before any game

_TABLE_RE = re.compile(r"team_ratings_(\d{4})_asof_(\d{8})\.csv$")


@dataclass(frozen=True)
class NcaabTeamRating:
    espn_id: str
    team: str
    adj_off: float
    adj_def: float
    tempo: float
    games: int
    prior_weight: float


@dataclass(frozen=True)
class NcaabRatingsTable:
    season: int
    as_of: dt.date
    source: str  # the table's path, or "computed:<label>" for a walk-forward build
    teams: Mapping[str, NcaabTeamRating]
    league_off: float
    league_tempo: float
    prior_season_fallback: bool  # True: last season's table, regressed, before this season's first game


@dataclass(frozen=True)
class NcaabGamePrior:
    home_id: str
    away_id: str
    neutral: bool
    possessions: float
    home_ppp: float
    away_ppp: float
    home_points: float
    away_points: float
    total: float
    home_margin: float
    ratings_season: int
    ratings_as_of: dt.date
    prior_season_fallback: bool
    home_games: int
    away_games: int


@dataclass(frozen=True)
class NcaabPriorRefusal:
    reason: str  # no_ratings_table | team_unrated
    detail: str


PriorResult = Union[NcaabGamePrior, NcaabPriorRefusal]


# ------------------------------------------------------------------ seasons

def espn_season_for(day: dt.date) -> int:
    """The ratings tables' season: the calendar year the season ENDS in."""
    return day.year + 1 if day.month >= 11 else day.year


# ------------------------------------------------------------------- tables

def ratings_dirs() -> list[Path]:
    roots = preferred_artifact_roots(__file__, env_var="SYNDICATE_NCAAB_SOURCE_ROOT", local_dir_name="ncaab_source")
    return [root / "data" / "processed" for root in roots]


def _table_files(dirs: Optional[Iterable[Path]] = None) -> list[tuple[int, dt.date, Path]]:
    found: dict[tuple[int, dt.date], Path] = {}
    for directory in dirs if dirs is not None else ratings_dirs():
        if not directory.is_dir():
            continue
        for path in directory.glob("team_ratings_*_asof_*.csv"):
            match = _TABLE_RE.search(path.name)
            if not match:
                continue
            key = (int(match.group(1)), dt.datetime.strptime(match.group(2), "%Y%m%d").date())
            found.setdefault(key, path)  # first root wins, as preferred_artifact_roots orders them
    return sorted((season, as_of, path) for (season, as_of), path in found.items())


def _f(value: object) -> Optional[float]:
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def table_from_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    season: int,
    as_of: dt.date,
    source: str,
    regress_toward_mean: float = 0.0,
) -> Optional[NcaabRatingsTable]:
    """A table from producer-shaped rows (CSV rows, or `compute_ratings` values with `espn_id`).

    Rows missing adj_off / adj_def / tempo are DROPPED, not filled: the team is
    then unrated and its games refuse.
    """
    parsed: list[tuple[str, str, float, float, float, int, float]] = []
    for row in rows:
        tid = str(row.get("espn_id") or "").strip()
        off, deff, tempo = _f(row.get("adj_off")), _f(row.get("adj_def")), _f(row.get("tempo"))
        if not tid or off is None or deff is None or tempo is None or tempo <= 0:
            continue
        games = int(_f(row.get("games")) or 0)
        prior_weight = _f(row.get("prior_weight")) or 0.0
        parsed.append((tid, str(row.get("team") or tid), off, deff, tempo, games, prior_weight))
    if not parsed:
        return None
    league_off = sum(p[2] for p in parsed) / len(parsed)
    league_def = sum(p[3] for p in parsed) / len(parsed)
    league_tempo = sum(p[4] for p in parsed) / len(parsed)
    keep = 1.0 - float(regress_toward_mean)
    teams = {
        tid: NcaabTeamRating(
            espn_id=tid,
            team=name,
            adj_off=league_off + keep * (off - league_off),
            adj_def=league_def + keep * (deff - league_def),
            tempo=league_tempo + keep * (tempo - league_tempo),
            games=0 if regress_toward_mean else games,
            prior_weight=1.0 if regress_toward_mean else prior_weight,
        )
        for tid, name, off, deff, tempo, games, prior_weight in parsed
    }
    return NcaabRatingsTable(
        season=season,
        as_of=as_of,
        source=source,
        teams=teams,
        league_off=league_off,
        league_tempo=league_tempo,
        prior_season_fallback=bool(regress_toward_mean),
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def table_for_game(game_date: dt.date, *, dirs: Optional[Iterable[Path]] = None) -> Union[NcaabRatingsTable, NcaabPriorRefusal]:
    """The newest table strictly before `game_date` for its season, else last season's newest, regressed."""
    season = espn_season_for(game_date)
    files = _table_files(dirs)
    this_season = [(s, a, p) for s, a, p in files if s == season and a < game_date]
    if this_season:
        s, a, p = this_season[-1]
        table = table_from_rows(_read_csv(p), season=s, as_of=a, source=str(p))
    else:
        earlier = [(s, a, p) for s, a, p in files if s < season]
        if not earlier:
            return NcaabPriorRefusal("no_ratings_table", f"no team_ratings_<season>_asof_*.csv before {game_date} in {[str(d) for d in (dirs or ratings_dirs())]}")
        s, a, p = earlier[-1]
        table = table_from_rows(_read_csv(p), season=s, as_of=a, source=str(p), regress_toward_mean=PRIOR_REGRESSION)
    if table is None:
        return NcaabPriorRefusal("no_ratings_table", f"{p} has no rated rows")
    return table


# -------------------------------------------------------------------- prior

def game_prior(table: NcaabRatingsTable, home_id: str, away_id: str, *, neutral: bool) -> PriorResult:
    home, away = table.teams.get(str(home_id)), table.teams.get(str(away_id))
    missing = [tid for tid, rating in ((str(home_id), home), (str(away_id), away)) if rating is None]
    if missing:
        return NcaabPriorRefusal("team_unrated", f"espn_id {','.join(missing)} not in {table.source} (as_of {table.as_of})")
    assert home is not None and away is not None
    possessions = home.tempo * away.tempo / table.league_tempo
    home_ppp = home.adj_off * away.adj_def / table.league_off / 100.0
    away_ppp = away.adj_off * home.adj_def / table.league_off / 100.0
    edge = 0.0 if neutral else HOME_POINTS / 2.0
    home_points = home_ppp * possessions + edge
    away_points = away_ppp * possessions - edge
    return NcaabGamePrior(
        home_id=home.espn_id,
        away_id=away.espn_id,
        neutral=bool(neutral),
        possessions=possessions,
        home_ppp=home_ppp,
        away_ppp=away_ppp,
        home_points=home_points,
        away_points=away_points,
        total=home_points + away_points,
        home_margin=home_points - away_points,
        ratings_season=table.season,
        ratings_as_of=table.as_of,
        prior_season_fallback=table.prior_season_fallback,
        home_games=home.games,
        away_games=away.games,
    )


def prior_for_game(game_date: dt.date, home_id: str, away_id: str, *, neutral: bool, dirs: Optional[Iterable[Path]] = None) -> PriorResult:
    table = table_for_game(game_date, dirs=dirs)
    if isinstance(table, NcaabPriorRefusal):
        return table
    return game_prior(table, home_id, away_id, neutral=neutral)
