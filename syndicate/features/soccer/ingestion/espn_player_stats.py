"""ESPN-based season player-stat aggregation for leagues without Understat.

Understat only covers the original big-five European leagues; football-
data.co.uk covers match history for a much wider set (including this
session's "next tier" -- Eredivisie, Primeira Liga, Championship, Belgian
Pro League) but carries no player-level data at all. ESPN's match-summary
rosters (the same source Phase 7/8 already use for confirmed lineups)
carry real per-match player stats too, so aggregating them across a season
produces per-90 rates for any league ESPN covers, independent of Understat.

Rates here are **true per-90**, derived from exact minutes played --
``espn_match_events.compute_minutes_played`` reconstructs each player's
on-pitch time from the match's substitution/red-card timeline, so a player
subbed on for ten minutes correctly contributes a tenth of a full
appearance's weight rather than counting the same as a 90-minute start
(the per-*appearance* proxy this module used before that existed).

HOW THESE ROWS COMPARE TO UNDERSTAT/ASA ROWS -- checked before wiring this
into the weekly producer, because ``player_props.build_usage_profiles``
normalises a squad's rates into shares that sum to ~1.0, and mixing two
different quantities inside one squad would mis-allocate volume silently.

  * **Same unit.** All three sources emit per-90 rates over real minutes.
    The "season-aggregated APPEARANCE RATES, not true per-90" caveat that
    older docstrings still carry describes the version of this module that
    predates ``compute_minutes_played``; rows have been tagged
    ``espn_true_per90`` since.
  * **Different estimator, same quantity.** ``xg_per90``/``xa_per90`` here
    are REALISED goals and assists per 90 -- ESPN publishes no xG. Understat
    and ASA put model xG/xA in those columns. Noisier at equal minutes, but
    the same quantity in expectation and the same units.
  * **Why the estimator difference is safe.** The source is a pure function
    of the LEAGUE (Understat for the big five, ASA for MLS, ESPN for the
    rest), so no squad -- and no league's ``players_*.csv`` set -- ever
    mixes them, and ``build_usage_profiles`` only ever compares rows to
    their own teammates. There is no path on which an ESPN row is
    normalised against an Understat one. ``test_soccer_espn_player_leagues``
    pins that as an invariant rather than leaving it as an observation.

The one thing that does NOT carry across is the COLUMN NAME for minutes:
these rows say ``minutes_played`` where Understat/ASA say ``minutes``.
`build_soccer_artifacts` reads both -- see `_minutes_series` there, and the
measurement that forced it.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from datetime import timedelta
from typing import Any

from syndicate.features.soccer.features.schedule import season_date_range
from syndicate.features.soccer.ingestion.espn_lineups import extract_match_player_rows
from syndicate.features.soccer.ingestion.espn_lineups import fetch_completed_events
from syndicate.features.soccer.ingestion.espn_lineups import fetch_match_summary
from syndicate.features.soccer.ingestion.espn_match_events import compute_minutes_played
from syndicate.features.soccer.ingestion.espn_match_events import extract_key_events
from syndicate.features.shared.timezone import central_today

_NOMINAL_MATCH_MINUTES = 90.0

#: Days per scoreboard window. ESPN's scoreboard endpoint silently truncates
#: around ~100 events per call (`espn_lineups.fetch_events` documents this), and
#: silent truncation here is the worst possible failure: the rows still look
#: like a season, they are just missing matches, and nothing downstream can
#: tell. The widest league this serves is the Championship -- 24 clubs, 12
#: matches a round, and midweek rounds make 6 rounds in a calendar month
#: realistic, i.e. ~72 events for a WHOLE month. Half a month halves that to
#: ~36 and leaves the truncation point nearly 3x away. The extra calls are
#: free next to the per-match summary fetches that dominate this module
#: (measured 2026-09-04: 4 leagues, 9-13s each end to end).
_WINDOW_DAYS = 15


def season_date_windows(
    league: str,
    season: int,
    *,
    today: date | None = None,
    window_days: int = _WINDOW_DAYS,
) -> list[str]:
    """``YYYYMMDD-YYYYMMDD`` windows covering the ALREADY-PLAYED part of a season.

    THESE CANNOT BE HARD-CODED. The producer that calls this runs weekly and
    forever, so a literal window list would silently stop covering the season
    the moment it rolled -- and the failure mode is not an error, it is a
    correct-looking roster built from last year's matches.

    Derived from `features.schedule.season_date_range`, which is the same
    function `default_season` is the inverse of, so the window set and the
    season label can never disagree. The end is clipped to TODAY: requesting
    months that have not happened yet costs a call per window and returns
    nothing, because `fetch_completed_events` keeps only `post` events.

    Returns `[]` when the season has not started, which is a real answer and
    not an error -- the caller decides whether that is "skip this week" or
    "this request made no sense".
    """
    today = today or central_today()
    start, end = season_date_range(league, int(season))
    end = min(end, today)
    if end < start:
        return []
    windows: list[str] = []
    cursor = start
    step = max(1, int(window_days))
    while cursor <= end:
        window_end = min(cursor + timedelta(days=step - 1), end)
        windows.append(f"{cursor:%Y%m%d}-{window_end:%Y%m%d}")
        cursor = window_end + timedelta(days=1)
    return windows


def aggregate_season_player_stats(
    league: str,
    *,
    date_windows: list[str],
    min_appearances: int = 3,
) -> list[dict[str, Any]]:
    """Season-aggregated true-per-90 player rows, shaped for
    ``player_props.build_usage_profiles`` (which reads ``shots_per90`` /
    ``xg_per90`` / ``xa_per90`` / ``expected_minutes_share``)."""
    completed = fetch_completed_events(league, date_windows=date_windows)
    team_match_counts: dict[str, int] = defaultdict(int)
    totals: dict[str, dict[str, Any]] = {}

    for event in completed:
        try:
            summary = fetch_match_summary(league, event["event_id"])
        except Exception:
            continue
        rows = extract_match_player_rows(summary, event_id=event["event_id"])
        if not rows:
            continue
        key_events = extract_key_events(summary)
        minutes_by_player = compute_minutes_played(key_events, rows)

        for team in {row["team"] for row in rows}:
            team_match_counts[team] += 1
        for row in rows:
            player_id = str(row.get("player_id") or "")
            minutes = minutes_by_player.get(player_id)
            if minutes is None:
                continue  # unused substitute: never actually entered this match
            key = player_id or f"name:{row.get('player_name')}"
            entry = totals.setdefault(
                key,
                {
                    "player_id": key,
                    "player_name": row["player_name"],
                    "team": row["team"],
                    "position": row["position"],
                    "is_goalkeeper": row["is_goalkeeper"],
                    "appearances": 0,
                    "starts": 0,
                    "minutes_played": 0.0,
                    "total_shots": 0.0,
                    "shots_on_target": 0.0,
                    "total_goals": 0.0,
                    "goal_assists": 0.0,
                },
            )
            entry["team"] = row["team"]  # most recent team -- handles a mid-season transfer reasonably
            entry["appearances"] += 1
            entry["starts"] += 1 if row["starter"] else 0
            entry["minutes_played"] += minutes
            entry["total_shots"] += row["total_shots"]
            entry["shots_on_target"] += row["shots_on_target"]
            entry["total_goals"] += row["total_goals"]
            entry["goal_assists"] += row["goal_assists"]

    rows_out: list[dict[str, Any]] = []
    for entry in totals.values():
        appearances = entry["appearances"]
        if appearances < min_appearances:
            continue
        minutes_played = entry["minutes_played"]
        nineties = minutes_played / _NOMINAL_MATCH_MINUTES if minutes_played > 0 else 0.0
        team_matches = team_match_counts.get(entry["team"], appearances)
        rows_out.append(
            {
                "league": league,
                "player_id": entry["player_id"],
                "player_name": entry["player_name"],
                "team": entry["team"],
                "position": entry["position"],
                "is_goalkeeper": entry["is_goalkeeper"],
                "appearances": appearances,
                "starts": entry["starts"],
                "minutes_played": round(minutes_played, 1),
                "shots_per90": round(entry["total_shots"] / nineties, 4) if nineties > 0 else 0.0,
                "xg_per90": round(entry["total_goals"] / nineties, 4) if nineties > 0 else 0.0,
                "xa_per90": round(entry["goal_assists"] / nineties, 4) if nineties > 0 else 0.0,
                "shot_on_target_rate": (
                    round(entry["shots_on_target"] / entry["total_shots"], 4) if entry["total_shots"] else None
                ),
                "expected_minutes_share": (
                    round(min(1.0, minutes_played / (team_matches * _NOMINAL_MATCH_MINUTES)), 4)
                    if team_matches
                    else None
                ),
                "source": "espn_true_per90",
            }
        )
    _shrink_goal_rates_toward_position(rows_out)
    return rows_out


#: Minutes at which a player's own goal/assist rate carries HALF the weight of the
#: positional prior. It is the curve `player_history._shrink_toward_prior` uses for
#: Understat and ASA rows, re-fitted for these: 180 beat 450, 900 and 1800 on
#: training log loss (lane soccer-anytime-scorer, 2026-09-15).
_RATE_STABILISATION_MINUTES = 180.0
_SHRUNK_GOAL_FIELDS = ("xg_per90", "xa_per90")


def _position_bucket(position: Any) -> str:
    """D / M / F / GK, BY KEYWORD.

    ESPN writes lineup SLOTS ("Center Left Defender", "Attacking Midfielder
    Right"), and "Substitute" for 460 of ~1,240 rows (2026-09-15). The
    first-token bucketing `player_history` uses on Understat's letter codes would
    split one position into "Center"/"Left"/"Attacking", and give a third of the
    rows a prior named after the bench. Anything unrecognised returns "?" and
    takes the league's outfield prior.
    """
    text = str(position or "").lower()
    if "goalkeeper" in text:
        return "GK"
    if "defender" in text or "back" in text or "sweeper" in text:
        return "D"
    if "midfielder" in text:
        return "M"
    if "forward" in text or "striker" in text or "wing" in text:
        return "F"
    return "?"


def _shrink_goal_rates_toward_position(rows: list[dict[str, Any]]) -> None:
    """Pull `xg_per90`/`xa_per90` toward the (league, position) minutes-weighted mean.

    The weight is `minutes_played / (minutes_played + 180)`. Mutates in place.

    THESE ROWS CARRY REALISED GOALS, so an unshrunk rate is exactly 0 for every
    player who has not scored yet. Measured 2026-09-15 on appeared players, 53%
    of the ESPN leagues' anytime-scorer prices were 0.000 (0.2% in the other six
    leagues, whose rates are already shrunk). Held out, shrinking cut the ESPN
    leagues' anytime log loss from 0.3551 to 0.2666.

    SHOTS ARE NOT SHRUNK. The conditional shot ladder was validated on these
    rows' raw shot rates. Goalkeepers are neither shrunk nor counted in a prior.
    """
    outfield = [row for row in rows if _position_bucket(row.get("position")) != "GK"]
    if not outfield:
        return

    def _minutes(row: dict[str, Any]) -> float:
        try:
            return max(0.0, float(row.get("minutes_played") or 0.0))
        except (TypeError, ValueError):
            return 0.0

    def _prior(group: list[dict[str, Any]]) -> dict[str, float] | None:
        total = sum(_minutes(row) for row in group)
        if total <= 0:
            return None
        return {
            field: sum(float(row.get(field) or 0.0) * _minutes(row) for row in group) / total
            for field in _SHRUNK_GOAL_FIELDS
        }

    league_prior = _prior(outfield) or {field: 0.0 for field in _SHRUNK_GOAL_FIELDS}
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in outfield:
        buckets[_position_bucket(row.get("position"))].append(row)
    for key, group in buckets.items():
        prior = (_prior(group) if key != "?" else None) or league_prior
        for row in group:
            minutes = _minutes(row)
            weight = minutes / (minutes + _RATE_STABILISATION_MINUTES)
            for field in _SHRUNK_GOAL_FIELDS:
                own = float(row.get(field) or 0.0)
                row[field] = round(weight * own + (1.0 - weight) * prior[field], 4)
            row["rate_own_weight"] = round(weight, 4)


__all__ = ["aggregate_season_player_stats", "season_date_windows"]
