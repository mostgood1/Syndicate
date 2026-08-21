"""Per-team game context: implied team total, spread, game total.

WHY THIS EXISTS. The NFL player-prop model is `Normal(rolling mean, rolling
stdev)` computed from a player's own prior games and nothing else. Measured
2026-08-20 against real closing prices over 64,007 bets, it returns **-7.35%**
(best price) / **-7.23%** (DraftKings). It is not uninformative -- fading it
loses 16.93% -- but it cannot clear the vig, and the structural reason is that
books price props off the game total and spread while this model is blind to
both. A receiver's yardage line moves several yards on the implied team total
alone.

THE INPUT IS ALREADY ON DISK. `schedules_games.csv` (nflverse) carries
`spread_line` and `total_line`, populated for **816 of 816** REG games across
2023-2025 (100%, measured 2026-08-20). No new capture is needed.

SIGN CONVENTION, taken from nflverse and verified against a real row rather
than assumed: `spread_line` is from the HOME team's perspective and POSITIVE
means the home team is favoured. `2023_01_DET_KC` carries `spread_line=4,
total_line=53` with KC at home, giving KC an implied 28.5 and DET 24.5, which
sums back to 53.

MECHANISM, NOT ESTIMATOR (`docs/ai_context/model_engine_standard.md` 4.4). This
changes what the projection DOES, and a player's rolling mean has already
absorbed the AVERAGE game script of the games in its own window. Consumers must
therefore normalise against the player's own historical context rather than
against the league -- see `implied_total_ratio` -- or they will double-count the
effect the calibration is already carrying. That doc records two mechanisms
added to a calibrated engine producing a negative interaction in 4 of 4 markets.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from typing import Any

from syndicate.features.nfl.sources import default_nfl_source_root


def schedule_paths(season: int) -> list:
    """Where a season's spread/total can be read from, best source first.

    `schedule_{season}.csv` FIRST, and this ordering is the whole reason this
    function exists rather than a constant. The nflverse dump
    (`tracking/nflverse/schedules_games.csv`) is what the 2023-2025 fit was run
    against, but it is **gitignored** (`.gitignore:96 data/nfl_source/tracking/`)
    and no script in this repo writes it -- so it exists on a developer machine
    and NOWHERE in production. Wiring the board to it produced a mechanism that
    was live, tested, deployed, and silently inert: `game_context` returned {},
    `implied_total_ratio` returned None, and the multiplier collapsed to 1.0 for
    every player. Measured on the served surface 2026-08-21:
    `/api/ops/artifacts/export?pattern=nfl_source/tracking/nflverse/
    schedules_games.csv` -> count 0, with the allowlist pattern confirmed
    present in the deployed commit, so that zero is FILE-ABSENT and not
    pattern-absent.

    `schedule_{season}.csv` carries the same `spread_line` / `total_line`
    columns, is what `sources.real_schedule_path` and `nfl_target_week` already
    read, and has a real production fetcher (`scripts/fetch_nfl_schedule.py`).

    The nflverse dump stays as a FALLBACK so the offline fit and backtest keep
    working on 2023-2025, which the per-season file does not cover locally.
    """
    from syndicate.features.nfl.sources import nfl_artifact_output_root

    # The ARTIFACT OUTPUT ROOT first, because that is where
    # scripts/fetch_nfl_schedule.py now writes (`#389`: the probing
    # `default_nfl_source_root` returns the ephemeral checkout, since the repo
    # mirror ships `upcoming_recs_*.csv` and the mounted disk does not). The
    # probed root stays as a fallback so a dev checkout still resolves.
    return [
        nfl_artifact_output_root() / f"schedule_{int(season)}.csv",
        default_nfl_source_root() / f"schedule_{int(season)}.csv",
        default_nfl_source_root() / "tracking" / "nflverse" / "schedules_games.csv",
    ]


@lru_cache(maxsize=8)
def game_context(season: int) -> dict[tuple[int, str], dict[str, Any]]:
    """{(week, team_abbr): context} for every REG team-game in *season*.

    Keys are (week, team) so a caller that knows a player's team for a week can
    look up that team's own side of the game -- the away team's implied total is
    not the home team's.
    """
    out: dict[tuple[int, str], dict[str, Any]] = {}
    path = next((candidate for candidate in schedule_paths(season) if candidate.exists()), None)
    if path is None:
        return out
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                row_season = int(row.get("season") or 0)
                week = int(row.get("week") or 0)
            except (TypeError, ValueError):
                continue
            # `schedule_{season}.csv` holds ONE season, so its `season` column is
            # redundant there; the shared nflverse dump holds many and the filter
            # is load-bearing. Applied to both rather than branching, so the two
            # sources cannot diverge in what they admit.
            if row_season != season or str(row.get("game_type") or "").strip() != "REG":
                continue
            try:
                spread = float(row.get("spread_line"))
                total = float(row.get("total_line"))
            except (TypeError, ValueError):
                # A game with no closing line is skipped, never defaulted to 0.
                # A zero spread and a missing spread are different facts and a
                # neutral default would make the second invisible (4.2).
                continue
            home = str(row.get("home_team") or "").strip()
            away = str(row.get("away_team") or "").strip()
            if not home or not away:
                continue
            home_implied = total / 2.0 + spread / 2.0
            away_implied = total / 2.0 - spread / 2.0
            out[(week, home)] = {
                "implied_total": home_implied,
                "opponent_implied_total": away_implied,
                "favoured_by": spread,
                "game_total": total,
                "is_home": True,
                "opponent": away,
                "game_id": str(row.get("game_id") or ""),
            }
            out[(week, away)] = {
                "implied_total": away_implied,
                "opponent_implied_total": home_implied,
                "favoured_by": -spread,
                "game_total": total,
                "is_home": False,
                "opponent": home,
                "game_id": str(row.get("game_id") or ""),
            }
    return out


def team_context(season: int, week: int, team: str) -> dict[str, Any] | None:
    return game_context(season).get((int(week), str(team or "").strip()))


def implied_total_ratio(
    season: int,
    week: int,
    team_by_week: dict[int, str],
    *,
    prior_weeks: list[int],
) -> float | None:
    """This game's implied team total / the player's OWN average implied total
    over the games his rolling rate was built from.

    SELF-NORMALISING BY DESIGN, and that is the whole point. Returning a ratio
    against the player's own history means the multiplier is exactly 1.0 when
    this week's game context matches what the rolling mean already absorbed, so
    the mechanism only moves a projection to the extent the context DIFFERS.
    Normalising against a league average instead would re-apply an effect the
    calibration is already carrying -- the double-count 4.4 warns about.

    Returns None when the context is unknown for either side, never 1.0: an
    unknown ratio and a neutral ratio must not be the same value, or an unfed
    lookup becomes invisible (4.2).
    """
    team = team_by_week.get(int(week))
    if not team:
        return None
    current = team_context(season, week, team)
    if not current:
        return None

    priors: list[float] = []
    for prior_week in prior_weeks:
        prior_team = team_by_week.get(int(prior_week))
        if not prior_team:
            continue
        prior = team_context(season, prior_week, prior_team)
        if prior:
            priors.append(float(prior["implied_total"]))
    if not priors:
        return None
    baseline = sum(priors) / len(priors)
    if baseline <= 0:
        return None
    return float(current["implied_total"]) / baseline


def favoured_by_delta(
    season: int,
    week: int,
    team_by_week: dict[int, str],
    *,
    prior_weeks: list[int],
) -> float | None:
    """This game's spread minus the player's own average spread over the games
    behind his rolling rate, in points.

    Separate from `implied_total_ratio` because it drives a DIFFERENT thing:
    implied total moves scoring (yards, TDs, receptions), while the spread moves
    the run/pass MIX -- a team favoured by two touchdowns runs more and throws
    less, at the same implied total. Same self-normalising discipline.
    """
    team = team_by_week.get(int(week))
    if not team:
        return None
    current = team_context(season, week, team)
    if not current:
        return None
    priors: list[float] = []
    for prior_week in prior_weeks:
        prior_team = team_by_week.get(int(prior_week))
        if not prior_team:
            continue
        prior = team_context(season, prior_week, prior_team)
        if prior:
            priors.append(float(prior["favoured_by"]))
    if not priors:
        return None
    return float(current["favoured_by"]) - (sum(priors) / len(priors))
