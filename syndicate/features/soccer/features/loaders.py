"""Feature loaders: ingested history -> SoccerSim simulation inputs.

Turns the ingestion layer's outputs into engine-ready inputs:

- ``compute_team_ratings``: per-team attack/defense ratings from xG
  performance history (Understat team rows; goals-based rows work as a
  fallback via ``team_rows_from_match_history``). Ratings are relative to
  the league mean and sized for the engine's rating seam (a ±0.35 cap
  moves the priors' attack/defense index by roughly ±0.17 after blending).
- ``build_soccer_match_features`` / ``build_soccer_simulation_input``:
  fixtures + ratings + player per-90 rows -> contracts objects, with
  team-name matching across sources and player team names rewritten to the
  fixture's naming so the adapter's side-matching works.
"""

from __future__ import annotations

from statistics import mean
from typing import Any

from syndicate.features.soccer.contracts import SoccerMatchFeatures
from syndicate.features.soccer.contracts import SoccerPlayerFeatures
from syndicate.features.soccer.contracts import SoccerSimulationInput
from syndicate.features.soccer.features.team_names import canonical_team_name
from syndicate.features.soccer.features.team_names import match_team_name

_RATING_SCALE = 0.55
_RATING_CAP = 0.35


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def team_rows_from_match_history(match_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert football-data match rows into per-team performance rows.

    Goals stand in for xG when no xG source covers the league, keeping
    ``compute_team_ratings`` source-agnostic.
    """
    team_rows: list[dict[str, Any]] = []
    for row in match_rows:
        home_goals = _safe_float(row.get("home_goals"))
        away_goals = _safe_float(row.get("away_goals"))
        if home_goals is None or away_goals is None:
            continue
        common = {"league": row.get("league"), "season": row.get("season"), "date": row.get("date")}
        team_rows.append({**common, "team": row.get("home_team"), "xg_for": home_goals, "xg_against": away_goals})
        team_rows.append({**common, "team": row.get("away_team"), "xg_for": away_goals, "xg_against": home_goals})
    return team_rows


def compute_team_ratings(
    team_history_rows: list[dict[str, Any]],
    *,
    as_of: str,
    window: int | None = None,
) -> dict[str, dict[str, float]]:
    """Per-team attack/defense ratings from per-match performance rows.

    Rows need ``team``, ``xg_for``, ``xg_against`` (Understat team-history
    rows match directly). ``window`` keeps only each team's most recent N
    rows.

    ``as_of`` IS REQUIRED, AND THAT IS THE WHOLE POINT (audit §7 #6).

    This function had no notion of time. It took ``rows[-window:]`` off
    whatever history it was handed, and `backtest_soccer_live_lens.run_backtest`
    computed it ONCE per league and then applied it to every match inside that
    season -- so a March match was scored using ratings built partly from May
    results. Every number in `data/soccer_source/*/validation/*_backtest_*.csv`
    was produced that way and cannot be cited.

    Required rather than defaulted, because the three call sites are NOT the
    same case and a default would silently pick the wrong one for two of them:

    - `backtest_soccer_live_lens` and `validate_soccer_vs_market` evaluate PAST
      matches and must pass **each match's own date**.
    - `build_soccer_artifacts` is PRODUCTION for FUTURE matches, where using all
      available history is correct; it passes the target date and its behaviour
      is unchanged, because a future date excludes nothing.

    STRICTLY BEFORE, BY CALENDAR DAY. A match cannot inform its own prediction,
    and same-day fixtures are excluded too: kickoff times within a day are not
    reliably ordered across these sources, so "earlier that day" is not a
    distinction this data can support. Conservative in the only safe direction.

    A row with NO USABLE DATE IS DROPPED, not admitted. It cannot be shown to
    predate `as_of`, and unknown must not take the permissive branch here of all
    places -- admitting undated rows is exactly the leak this parameter exists
    to close. Drops are counted and printed, because a ratings set that silently
    collapses to empty is indistinguishable from a league with no history.
    """
    cutoff = str(as_of or "").strip()[:10]
    if not cutoff:
        raise ValueError("compute_team_ratings requires an as_of date (YYYY-MM-DD)")

    by_team: dict[str, list[dict[str, Any]]] = {}
    dropped_undated = 0
    dropped_future = 0
    for row in team_history_rows:
        team = str(row.get("team") or "").strip()
        if not team:
            continue
        if _safe_float(row.get("xg_for")) is None or _safe_float(row.get("xg_against")) is None:
            continue
        row_day = str(row.get("date") or "").strip()[:10]
        if not row_day:
            dropped_undated += 1
            continue
        if row_day >= cutoff:
            dropped_future += 1
            continue
        by_team.setdefault(team, []).append(row)

    # Sort explicitly rather than trusting the caller. `window` takes the LAST N
    # rows, so an unsorted input silently selects an arbitrary subset once
    # filtering has removed rows from the middle -- and the old docstring's
    # "rows are assumed chronologically ordered" was an assumption nothing
    # checked.
    for rows in by_team.values():
        rows.sort(key=lambda row: str(row.get("date") or ""))

    if dropped_undated:
        print(
            f"[soccer_ratings] AS_OF_DROPPED_UNDATED as_of={cutoff} "
            f"rows={dropped_undated} teams_with_history={len(by_team)}",
            flush=True,
        )

    all_xg_for: list[float] = []
    for rows in by_team.values():
        selected = rows[-window:] if window else rows
        all_xg_for.extend(float(row["xg_for"]) for row in selected)
    league_mean = mean(all_xg_for) if all_xg_for else 1.35
    if league_mean <= 0:
        league_mean = 1.35

    ratings: dict[str, dict[str, float]] = {}
    for team, rows in by_team.items():
        selected = rows[-window:] if window else rows
        xg_for = mean(float(row["xg_for"]) for row in selected)
        xg_against = mean(float(row["xg_against"]) for row in selected)
        ppda_values = [value for value in (_safe_float(row.get("ppda")) for row in selected) if value is not None]
        ratings[team] = {
            "attack_rating": round(_clamp((xg_for / league_mean - 1.0) * _RATING_SCALE, -_RATING_CAP, _RATING_CAP), 4),
            "defense_rating": round(_clamp((1.0 - xg_against / league_mean) * _RATING_SCALE, -_RATING_CAP, _RATING_CAP), 4),
            "xg_for_per_match": round(xg_for, 4),
            "xg_against_per_match": round(xg_against, 4),
            "ppda": round(mean(ppda_values), 4) if ppda_values else 0.0,
            "matches": float(len(selected)),
        }
    return ratings


def _rating_for(ratings: dict[str, dict[str, float]], team_name: str) -> tuple[dict[str, float], bool]:
    matched = match_team_name(team_name, list(ratings))
    if matched is None:
        return {"attack_rating": 0.0, "defense_rating": 0.0}, False
    return ratings[matched], True


def build_soccer_match_features(
    *,
    league: str,
    date: str,
    home_team: str,
    away_team: str,
    ratings: dict[str, dict[str, float]],
    match_id: str | None = None,
    market_features: dict[str, Any] | None = None,
    knockout: bool = False,
    home_starter_ids: tuple[str, ...] = (),
    away_starter_ids: tuple[str, ...] = (),
) -> SoccerMatchFeatures:
    home_rating, home_matched = _rating_for(ratings, home_team)
    away_rating, away_matched = _rating_for(ratings, away_team)
    team_metrics = {
        "home_attack_rating": home_rating.get("attack_rating", 0.0),
        "home_defense_rating": home_rating.get("defense_rating", 0.0),
        "away_attack_rating": away_rating.get("attack_rating", 0.0),
        "away_defense_rating": away_rating.get("defense_rating", 0.0),
    }
    return SoccerMatchFeatures(
        league=league,
        date=date,
        match_id=match_id or f"{league}_{date}_{canonical_team_name(home_team)}_{canonical_team_name(away_team)}".replace(" ", "_"),
        home_team=home_team,
        away_team=away_team,
        team_metrics=team_metrics,
        market_features=dict(market_features or {}),
        knockout=knockout,
        home_starter_ids=tuple(home_starter_ids),
        away_starter_ids=tuple(away_starter_ids),
        adapter_metadata={
            "home_rating_matched": home_matched,
            "away_rating_matched": away_matched,
            "home_rating_detail": dict(home_rating),
            "away_rating_detail": dict(away_rating),
        },
    )


def build_soccer_player_features(
    player_rows: list[dict[str, Any]],
    *,
    league: str,
    date: str,
    fixture_teams: list[str] | tuple[str, ...],
) -> tuple[SoccerPlayerFeatures, ...]:
    """Select ingested per-90 player rows for the fixture teams.

    Player team names are rewritten to the fixture's naming so the
    adapter's home/away side matching lines up regardless of source.
    """
    features: list[SoccerPlayerFeatures] = []
    dropped_teams: dict[str, int] = {}
    for row in player_rows:
        source_team = str(row.get("team") or "")
        fixture_team = match_team_name(source_team, fixture_teams)
        if fixture_team is None:
            # #148 follow-up. Same "no error path for an unmatched case"
            # shape as #146's _load_player_rows -- a roster-CSV team name
            # that doesn't resolve against this fixture's ESPN team names
            # (a rename, a promoted/relegated club, a data-source spelling
            # mismatch) silently vanished every one of that team's players
            # from the fixture's props, with nothing anywhere to show it
            # happened. Not currently firing for any tracked league
            # (confirmed team-name matching succeeds for all of them as of
            # 2026-07-30), but worth a visible signal instead of a silent
            # zero the next time a roster/fixture naming mismatch appears.
            dropped_teams[source_team] = dropped_teams.get(source_team, 0) + 1
            continue
        usage_metrics = {
            key: row.get(key)
            for key in (
                "shots_per90",
                "xg_per90",
                "xa_per90",
                "goals_per90",
                "assists_per90",
                "key_passes_per90",
                "expected_minutes_share",
                "minutes",
                "games",
                "is_goalkeeper",
                "penalty_taker",
                "set_piece_taker",
            )
            if row.get(key) is not None
        }
        features.append(
            SoccerPlayerFeatures(
                league=league,
                date=date,
                player_id=str(row.get("player_id") or ""),
                player_name=str(row.get("player_name") or ""),
                team=fixture_team,
                position=str(row.get("position") or ""),
                usage_metrics=usage_metrics,
                adapter_metadata={"source_team": source_team, "source": row.get("source")},
            )
        )
    if dropped_teams:
        print(
            f"[loaders] SOCCER_PLAYER_ROWS_UNMATCHED_TEAM league={league} date={date} "
            f"fixture_teams={list(fixture_teams)} dropped_by_source_team={dropped_teams}",
            flush=True,
        )
    return tuple(features)


def build_soccer_simulation_input(
    *,
    league: str,
    date: str,
    fixtures: list[dict[str, Any]],
    ratings: dict[str, dict[str, float]],
    player_rows: list[dict[str, Any]] | None = None,
    simulations: int | None = None,
    knockout: bool = False,
) -> SoccerSimulationInput:
    """Assemble a full simulation input from fixtures + ratings (+ players).

    Fixtures are ``{"home_team", "away_team"}`` dicts, optionally carrying
    ``match_id``, ``market_features``, and confirmed/projected lineups as
    ``home_starter_ids`` / ``away_starter_ids`` (see
    ``soccersim.player_props.build_usage_profiles`` for the id format).
    """
    matches = tuple(
        build_soccer_match_features(
            league=league,
            date=date,
            home_team=str(fixture.get("home_team") or ""),
            away_team=str(fixture.get("away_team") or ""),
            ratings=ratings,
            match_id=fixture.get("match_id"),
            market_features=fixture.get("market_features"),
            knockout=knockout or bool(fixture.get("knockout")),
            home_starter_ids=tuple(fixture.get("home_starter_ids") or ()),
            away_starter_ids=tuple(fixture.get("away_starter_ids") or ()),
        )
        for fixture in fixtures
    )
    fixture_teams = [team for match in matches for team in (match.home_team, match.away_team)]
    players: tuple[SoccerPlayerFeatures, ...] = ()
    if player_rows:
        players = build_soccer_player_features(player_rows, league=league, date=date, fixture_teams=fixture_teams)
    metadata: dict[str, Any] = {}
    if simulations is not None:
        metadata["simulations"] = int(simulations)
    return SoccerSimulationInput(
        league=league,
        date=date,
        matches=matches,
        players=players,
        metadata=metadata,
        adapter_metadata={"source": "soccer_feature_loaders", "rated_teams": len(ratings)},
    )


__all__ = [
    "build_soccer_match_features",
    "build_soccer_player_features",
    "build_soccer_simulation_input",
    "compute_team_ratings",
    "team_rows_from_match_history",
]
