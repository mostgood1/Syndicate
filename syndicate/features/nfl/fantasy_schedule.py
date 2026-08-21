"""The 2026 schedule, and the MARKET-IMPLIED scoring environment built off it.

Why the market and not the sim
------------------------------
Syndicate has an NFL game simulator (smartsim2), and this engine deliberately
does not use it for game environment. ``.syndicate/state.md``
``[football-smartsim2]`` measured, over 751 clean out-of-sample games:

    actual = a + b*market + w*(model - market)
    b = +0.990  CI [0.909, 1.076]   <- the closing line is unbiased
    w = -0.028  CI [-0.130, +0.069] <- the model's deviation carries NO signal

A model that is strictly dominated by the market is a bad input to a fantasy
projection for the same reason it is a bad input to a bet. So team scoring
environment comes from ``spread_line``/``total_line`` -- real posted numbers,
free and local in the nflverse schedule (``state.md``: "NFL CLOSING LINES ARE
FREE AND LOCAL -- do not buy them") -- and from prior-season rates where no
line exists yet.

``spread_line`` is the HOME MARGIN. Verified on 2025: corr(spread_line,
home_score - away_score) = +0.504 over 272 games, mean spread +1.5 against a
mean home margin of +2.07.

Coverage, measured 2026-08-21 on the local mirror: **112 of 272** 2026 games
carry a line (weeks 1-7, 9-12, 16), and **all 32 teams appear in 6-9 of them**.
That is enough to fit a team rating from the market and project the other 160
games, which is what ``market_team_ratings`` does. It is NOT enough to read a
per-game environment straight off the line for every week, and this module
never pretends otherwise -- every projected game says whether its number came
from a real line or from the fitted rating.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import csv
from pathlib import Path
from typing import Any
from typing import Iterable

from syndicate.features.nfl.sources import _resolve_nfl_tracking_path


# League-average points per team per game, used to centre the ratings fit. Not
# a tuned constant: it is re-derived from the lined games themselves whenever
# any exist, and this literal is only the cold-start fallback.
_FALLBACK_LEAGUE_POINTS_PER_TEAM = 22.5

# Iterations for the alternating ratings fit. The system is small (32 offense +
# 32 defense + home-field over ~224 observations) and converges to <0.01 points
# within ~30 passes; 200 is cheap insurance, not tuning.
_RATING_FIT_ITERATIONS = 200

# How strongly a team's market rating is shrunk toward the league mean when it
# has few lined games. Chosen as "one game of evidence is worth about a sixth
# of a full read" -- with the measured 6-9 lined games per team this leaves
# 79-85% weight on the market, and it exists only so the fit degrades smoothly
# if a future season's lookahead coverage is thinner. It is NOT fitted, and
# nothing downstream is calibrated against it.
_RATING_SHRINKAGE_GAMES = 1.5


def schedule_path() -> Path:
    return _resolve_nfl_tracking_path(Path("tracking") / "nflverse" / "schedules_games.csv")


@lru_cache(maxsize=8)
def load_schedule_rows(season: int) -> tuple[dict[str, str], ...]:
    """Regular-season schedule rows for *season*, in schedule order.

    Empty when the schedule file is not on this substrate -- an UNMEASURED
    signal, not "the season has no games".
    """
    path = schedule_path()
    if not path.is_file():
        return ()
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("season") != str(season):
                continue
            if row.get("game_type") != "REG":
                continue
            rows.append(row)
    rows.sort(key=lambda row: (int(row.get("week") or 0), row.get("gameday") or ""))
    return tuple(rows)


@dataclass(frozen=True)
class GameEnvironment:
    """One team's scoring environment for one game."""

    game_id: str
    season: int
    week: int
    team: str
    opponent: str
    is_home: bool
    implied_points: float
    opponent_implied_points: float
    total: float
    spread: float
    #: "market_line" when a real posted line fed this row, "fitted_rating" when
    #: it came from the ratings model. Never absent -- the payload must be able
    #: to say which, per model_engine_standard.md s3b.
    basis: str


def _number(raw: Any) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text == "NA":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _lined_observations(season: int) -> list[tuple[str, str, bool, float]]:
    """``(team, opponent, is_home, implied_points)`` for every side of every
    game that carries BOTH a spread and a total."""
    observations: list[tuple[str, str, bool, float]] = []
    for row in load_schedule_rows(season):
        spread = _number(row.get("spread_line"))
        total = _number(row.get("total_line"))
        if spread is None or total is None:
            continue
        home, away = row["home_team"], row["away_team"]
        home_points = (total + spread) / 2.0
        away_points = (total - spread) / 2.0
        observations.append((home, away, True, home_points))
        observations.append((away, home, False, away_points))
    return observations


@dataclass(frozen=True)
class MarketTeamRatings:
    """A market-fitted scoring model: what each team scores and allows."""

    season: int
    league_mean: float
    home_field: float
    offense: dict[str, float]
    defense: dict[str, float]
    lined_games: dict[str, int]
    total_lined_games: int

    def implied_points(self, team: str, opponent: str, is_home: bool) -> float:
        return (
            self.league_mean
            + self.offense.get(team, 0.0)
            + self.defense.get(opponent, 0.0)
            + (self.home_field if is_home else -self.home_field)
        )


@lru_cache(maxsize=8)
def market_team_ratings(season: int) -> MarketTeamRatings:
    """Fit per-team offense/defense scoring ratings to the posted lines.

    Model: ``implied_points(team vs opp) = mu + o_team + d_opp +/- h``, fitted
    by alternating least squares -- solve each block holding the others fixed,
    re-centre so the offense and defense blocks each sum to zero, repeat. This
    is a small ridge-free system and the alternating solve is exact at its
    fixed point; it is written in the standard library on purpose, following
    the same decision made for the NFL prop model (``state.md``
    ``[nfl-player-props-model]``: "deliberately stdlib-only, no scipy").

    Each team's rating is then shrunk toward zero by its own lined-game count,
    so a team the market has priced six times is not treated as equal evidence
    to one priced nine times.

    Returns a rating with empty blocks when no lined games exist. A caller
    must treat that as UNMEASURED and fall back to prior-season rates, which
    is what ``team_environments`` does.
    """
    observations = _lined_observations(season)
    teams = sorted({team for team, _, _, _ in observations})
    if not observations or not teams:
        return MarketTeamRatings(
            season=season,
            league_mean=_FALLBACK_LEAGUE_POINTS_PER_TEAM,
            home_field=0.0,
            offense={},
            defense={},
            lined_games={},
            total_lined_games=0,
        )

    league_mean = sum(points for _, _, _, points in observations) / len(observations)
    home_points = [points for _, _, is_home, points in observations if is_home]
    away_points = [points for _, _, is_home, points in observations if not is_home]
    home_field = 0.0
    if home_points and away_points:
        home_field = (sum(home_points) / len(home_points) - sum(away_points) / len(away_points)) / 2.0

    offense = {team: 0.0 for team in teams}
    defense = {team: 0.0 for team in teams}

    for _ in range(_RATING_FIT_ITERATIONS):
        offense_sums: dict[str, list[float]] = {team: [] for team in teams}
        for team, opponent, is_home, points in observations:
            residual = points - league_mean - defense.get(opponent, 0.0) - (home_field if is_home else -home_field)
            offense_sums[team].append(residual)
        offense = {
            team: (sum(values) / len(values) if values else 0.0) for team, values in offense_sums.items()
        }
        centre = sum(offense.values()) / len(offense)
        offense = {team: value - centre for team, value in offense.items()}

        defense_sums: dict[str, list[float]] = {team: [] for team in teams}
        for team, opponent, is_home, points in observations:
            residual = points - league_mean - offense.get(team, 0.0) - (home_field if is_home else -home_field)
            defense_sums[opponent].append(residual)
        defense = {
            team: (sum(values) / len(values) if values else 0.0) for team, values in defense_sums.items()
        }
        centre = sum(defense.values()) / len(defense)
        defense = {team: value - centre for team, value in defense.items()}

    lined_games: dict[str, int] = {team: 0 for team in teams}
    for team, _, _, _ in observations:
        lined_games[team] += 1

    def shrink(value: float, team: str) -> float:
        count = lined_games.get(team, 0)
        if count <= 0:
            return 0.0
        return value * (count / (count + _RATING_SHRINKAGE_GAMES))

    return MarketTeamRatings(
        season=season,
        league_mean=league_mean,
        home_field=home_field,
        offense={team: shrink(value, team) for team, value in offense.items()},
        defense={team: shrink(value, team) for team, value in defense.items()},
        lined_games=lined_games,
        total_lined_games=len(observations) // 2,
    )


def team_environments(season: int) -> dict[str, list[GameEnvironment]]:
    """Every team's full-season list of per-game scoring environments.

    A game with a posted line uses the line directly (``basis="market_line"``).
    A game without one is projected from the fitted ratings
    (``basis="fitted_rating"``). Nothing is silently interpolated.
    """
    ratings = market_team_ratings(season)
    environments: dict[str, list[GameEnvironment]] = {}

    for row in load_schedule_rows(season):
        home, away = row["home_team"], row["away_team"]
        week = int(row.get("week") or 0)
        spread = _number(row.get("spread_line"))
        total = _number(row.get("total_line"))

        if spread is not None and total is not None:
            home_points = (total + spread) / 2.0
            away_points = (total - spread) / 2.0
            basis = "market_line"
        else:
            home_points = ratings.implied_points(home, away, is_home=True)
            away_points = ratings.implied_points(away, home, is_home=False)
            total = home_points + away_points
            spread = home_points - away_points
            basis = "fitted_rating"

        environments.setdefault(home, []).append(
            GameEnvironment(
                game_id=row["game_id"],
                season=season,
                week=week,
                team=home,
                opponent=away,
                is_home=True,
                implied_points=home_points,
                opponent_implied_points=away_points,
                total=total,
                spread=spread,
                basis=basis,
            )
        )
        environments.setdefault(away, []).append(
            GameEnvironment(
                game_id=row["game_id"],
                season=season,
                week=week,
                team=away,
                opponent=home,
                is_home=False,
                implied_points=away_points,
                opponent_implied_points=home_points,
                total=total,
                spread=-spread,
                basis=basis,
            )
        )

    for games in environments.values():
        games.sort(key=lambda game: game.week)
    return environments


def bye_week(season: int, team: str) -> int | None:
    """The week *team* does not play. ``None`` when the schedule is absent or
    the team plays every week in the horizon."""
    environments = team_environments(season)
    games = environments.get(team) or []
    if not games:
        return None
    played = {game.week for game in games}
    horizon = range(1, max(played) + 1)
    missing = [week for week in horizon if week not in played]
    return missing[0] if missing else None


def schedule_substrate(season: int) -> dict[str, Any]:
    path = schedule_path()
    rows = load_schedule_rows(season)
    lined = sum(
        1
        for row in rows
        if _number(row.get("spread_line")) is not None and _number(row.get("total_line")) is not None
    )
    return {
        "season": season,
        "path": str(path),
        "exists": path.is_file(),
        "regular_season_games": len(rows),
        "games_with_market_line": lined,
    }
